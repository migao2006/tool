from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import final
from urllib.parse import parse_qs, urlsplit

import pytest

from src.data.ingestion.fugle_adjusted_probe import (
    FugleAdjustedProbe,
    FugleAdjustedProbeError,
    validate_probe_request,
)
from src.data.providers.contracts import ProviderPayload
from src.data.providers.fugle import FugleClient
from src.data.providers.http import JsonHttpClient, TransportResponse


ROOT = Path(__file__).resolve().parents[1]


def _payload(*, adjusted: bool, rows: list[dict[str, object]]) -> ProviderPayload:
    body = {
        "symbol": "2330",
        "timeframe": "D",
        "data": rows,
    }
    canonical = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return ProviderPayload(
        provider="FUGLE",
        dataset="historical_candles",
        source_version="marketdata.v1.0",
        source_url=(
            "https://api.fugle.tw/marketdata/v1.0/stock/"
            f"historical/candles/2330?adjusted={str(adjusted).lower()}"
        ),
        retrieved_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        payload_sha256=sha256(canonical).hexdigest(),
        payload=body,
        request_metadata={"symbol": "2330", "adjusted": str(adjusted).lower()},
    )


def _row(day: str, close: object, *, open_price: object = 100) -> dict[str, object]:
    return {
        "date": day,
        "open": open_price,
        "high": 110,
        "low": 90,
        "close": close,
    }


@final
class FakeFugleClient:
    def __init__(self, raw: ProviderPayload, adjusted: ProviderPayload) -> None:
        self.raw = raw
        self.adjusted = adjusted
        self.calls: list[bool] = []

    def historical_candles(
        self,
        symbol: str,
        *,
        start_date: date | str,
        end_date: date | str,
        adjusted: bool = False,
    ) -> ProviderPayload:
        assert symbol == "2330"
        assert start_date == date(2025, 5, 1)
        assert end_date == date(2025, 7, 31)
        self.calls.append(adjusted)
        return self.adjusted if adjusted else self.raw


def test_probe_confirms_access_without_leaking_price_rows() -> None:
    client = FakeFugleClient(
        _payload(
            adjusted=False,
            rows=[_row("2025-06-10", 101), _row("2025-06-11", 102)],
        ),
        _payload(
            adjusted=True,
            rows=[_row("2025-06-10", "100.5"), _row("2025-06-11", 102)],
        ),
    )
    sleeps: list[float] = []

    summary = FugleAdjustedProbe(
        client=client,
        sleep_fn=sleeps.append,
    ).run(
        symbol="2330",
        start_date=date(2025, 5, 1),
        end_date=date(2025, 7, 31),
        pacing_seconds=1,
    )

    assert client.calls == [False, True]
    assert sleeps == [1]
    assert summary.adjusted_access_confirmed is True
    assert summary.comparable_date_count == 2
    assert summary.differing_date_count == 1
    assert summary.interpretation == "ADJUSTED_SERIES_DIFFERS"
    assert summary.training_ready is False
    assert summary.writes_performed == 0
    serialized = json.dumps(summary.to_dict())
    assert '"open"' not in serialized
    assert '"close"' not in serialized
    assert "100.5" not in serialized


def test_probe_reports_inconclusive_window_without_claiming_adjustment() -> None:
    rows = [_row("2025-06-10", 101)]
    summary = FugleAdjustedProbe(
        client=FakeFugleClient(
            _payload(adjusted=False, rows=rows),
            _payload(adjusted=True, rows=rows),
        ),
        sleep_fn=lambda _: None,
    ).run(
        symbol="2330",
        start_date=date(2025, 5, 1),
        end_date=date(2025, 7, 31),
        pacing_seconds=0,
    )

    assert summary.adjusted_access_confirmed is True
    assert summary.differing_date_count == 0
    assert summary.interpretation == "ACCESS_CONFIRMED_NO_DIFFERENCE_IN_WINDOW"
    assert summary.economic_validation_status == "NOT_VALIDATED"


@pytest.mark.parametrize(
    ("start", "end", "pacing", "reason_code"),
    [
        (
            date(2025, 7, 2),
            date(2025, 7, 1),
            0,
            "FUGLE_ADJUSTED_PROBE_DATE_RANGE_INVALID",
        ),
        (
            date(2024, 1, 1),
            date(2025, 1, 2),
            0,
            "FUGLE_ADJUSTED_PROBE_DATE_RANGE_LIMIT",
        ),
        (
            date(2025, 1, 1),
            date(2025, 1, 2),
            -1,
            "FUGLE_ADJUSTED_PROBE_PACING_INVALID",
        ),
    ],
)
def test_probe_rejects_unbounded_requests(
    start: date,
    end: date,
    pacing: float,
    reason_code: str,
) -> None:
    with pytest.raises(FugleAdjustedProbeError) as captured:
        _ = validate_probe_request(
            symbol="2330",
            start_date=start,
            end_date=end,
            pacing_seconds=pacing,
        )
    assert captured.value.reason_code == reason_code


@pytest.mark.parametrize(
    ("rows", "reason_code"),
    [
        ([], "FUGLE_ADJUSTED_PROBE_EMPTY"),
        (
            [_row("2025-06-10", 101), _row("2025-06-10", 102)],
            "FUGLE_ADJUSTED_PROBE_DUPLICATE_DATE",
        ),
        (
            [_row("2026-06-10", 101)],
            "FUGLE_ADJUSTED_PROBE_DATE_OUTSIDE_REQUEST",
        ),
        (
            [
                {
                    "date": "2025-06-10",
                    "open": 120,
                    "high": 110,
                    "low": 90,
                    "close": 101,
                }
            ],
            "FUGLE_ADJUSTED_PROBE_OHLC_INVALID",
        ),
    ],
)
def test_probe_fails_closed_on_malformed_adjusted_rows(
    rows: list[dict[str, object]],
    reason_code: str,
) -> None:
    client = FakeFugleClient(
        _payload(adjusted=False, rows=[_row("2025-06-10", 101)]),
        _payload(adjusted=True, rows=rows),
    )
    with pytest.raises(FugleAdjustedProbeError) as captured:
        _ = FugleAdjustedProbe(client=client, sleep_fn=lambda _: None).run(
            symbol="2330",
            start_date=date(2025, 5, 1),
            end_date=date(2025, 7, 31),
            pacing_seconds=0,
        )
    assert captured.value.reason_code == reason_code


@final
class CapturingTransport:
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.headers: list[Mapping[str, str]] = []

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> TransportResponse:
        _ = timeout
        self.urls.append(url)
        self.headers.append(headers)
        return TransportResponse(
            status_code=200,
            headers={"Content-Type": "application/json"},
            body=json.dumps({"data": [_row("2025-06-10", 101)]}).encode(),
        )


def test_fugle_client_sends_adjusted_as_query_and_keeps_key_out_of_url() -> None:
    transport = CapturingTransport()
    client = FugleClient(
        api_key="private-test-key",
        http=JsonHttpClient(transport=transport, retry_backoff_seconds=0),
    )

    payload = client.historical_candles(
        "2330",
        start_date=date(2025, 5, 1),
        end_date=date(2025, 7, 31),
        adjusted=True,
    )

    query = parse_qs(urlsplit(transport.urls[0]).query)
    assert query["adjusted"] == ["true"]
    assert query["timeframe"] == ["D"]
    assert "private-test-key" not in transport.urls[0]
    assert transport.headers[0]["X-API-KEY"] == "private-test-key"
    assert payload.request_metadata["adjusted"] == "true"


def test_workflow_is_manual_read_only_and_does_not_upload_raw_payload() -> None:
    workflow = (ROOT / ".github/workflows/probe-fugle-adjusted.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "push:" not in workflow
    assert "FUGLE_API_KEY: ${{ secrets.FUGLE_API_KEY }}" in workflow
    assert "SUPABASE" not in workflow
    assert "R2_" not in workflow
    assert "upload-artifact" not in workflow
    assert "probe_fugle_adjusted" in workflow
