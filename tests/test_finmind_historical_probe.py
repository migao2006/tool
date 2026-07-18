from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from typing import final

import pytest

from src.data.ingestion.finmind_historical_probe import (
    FinMindHistoricalProbe,
    FinMindProbeError,
    validate_probe_request,
)
from src.data.providers.contracts import ProviderPayload
from src.data.providers.errors import ProviderHttpError, ProviderPayloadError
from src.data.providers.finmind import FinMindClient
from src.data.providers.http import JsonHttpClient, TransportResponse


def _payload(dataset: str, body: object) -> ProviderPayload:
    canonical = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return ProviderPayload(
        provider="FINMIND",
        dataset=dataset,
        source_version="test",
        source_url="https://api.finmindtrade.com/api/v4/data",
        retrieved_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
        payload_sha256=sha256(canonical).hexdigest(),
        payload=body,
    )


@final
class FakeProbeClient:
    def __init__(self, rows_by_symbol: Mapping[str, list[dict[str, object]]]) -> None:
        self.rows_by_symbol: Mapping[str, list[dict[str, object]]] = rows_by_symbol
        self.calls: list[str] = []

    def fetch_quota(self) -> ProviderPayload:
        self.calls.append("quota")
        return _payload(
            "api_quota",
            {"user_count": 10, "api_request_limit": 600, "extra": "not-reported"},
        )

    def fetch(
        self,
        dataset: str,
        *,
        data_id: str | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> ProviderPayload:
        assert dataset == "daily_bars"
        assert isinstance(data_id, str)
        _ = (start_date, end_date)
        self.calls.append(data_id)
        return _payload(
            "daily_bars",
            {"status": 200, "data": self.rows_by_symbol[data_id]},
        )


def test_probe_is_serial_paced_and_emits_only_audit_metadata() -> None:
    client = FakeProbeClient(
        {
            "2330": [
                {"stock_id": "2330", "date": "2026-07-01", "close": 1000},
                {"stock_id": "2330", "date": "2026-07-02", "close": 1010},
            ],
            "2317": [
                {"stock_id": "2317", "date": "2026-07-01", "close": 200},
            ],
        }
    )
    sleeps: list[float] = []

    summary = FinMindHistoricalProbe(
        client=client,
        sleep_fn=sleeps.append,
    ).run(
        symbols=("2330", "2317"),
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        pacing_seconds=7.5,
    )

    assert client.calls == ["quota", "2330", "2317"]
    assert sleeps == [7.5, 7.5]
    assert summary.total_rows == 3
    assert summary.symbols[0].minimum_date == "2026-07-01"
    assert summary.symbols[0].maximum_date == "2026-07-02"
    assert summary.symbols[0].unique_symbols == 1
    assert summary.symbols[0].response_bytes > 0
    assert summary.symbols[0].suspected_truncation is False
    serialized = json.dumps(summary.to_dict())
    assert "close" not in serialized
    assert "not-reported" not in serialized
    assert '"data"' not in serialized


def test_empty_response_is_reported_as_suspected_not_silently_complete() -> None:
    summary = FinMindHistoricalProbe(
        client=FakeProbeClient({"9999": []}),
        sleep_fn=lambda _: None,
    ).run(
        symbols=("9999",),
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        pacing_seconds=0,
    )

    assert summary.symbols[0].suspected_truncation is True
    assert summary.symbols[0].truncation_reasons == ("EMPTY_RESPONSE",)
    assert summary.coverage_assessment == "HEURISTIC_ONLY_NOT_TRAINING_READY"
    assert summary.writes_performed == 0


@pytest.mark.parametrize(
    ("symbols", "start", "end", "reason_code"),
    [
        ((), date(2026, 1, 1), date(2026, 1, 2), "FINMIND_PROBE_SYMBOLS_REQUIRED"),
        (
            tuple(str(index) for index in range(21)),
            date(2026, 1, 1),
            date(2026, 1, 2),
            "FINMIND_PROBE_SYMBOL_LIMIT",
        ),
        (
            ("2330", "2330"),
            date(2026, 1, 1),
            date(2026, 1, 2),
            "FINMIND_PROBE_DUPLICATE_SYMBOL",
        ),
        (
            ("2330",),
            date(2026, 1, 2),
            date(2026, 1, 1),
            "FINMIND_PROBE_DATE_RANGE_INVALID",
        ),
        (
            ("2330",),
            date(2020, 1, 1),
            date(2025, 1, 2),
            "FINMIND_PROBE_DATE_RANGE_LIMIT",
        ),
    ],
)
def test_probe_rejects_unbounded_or_ambiguous_requests(
    symbols: tuple[str, ...],
    start: date,
    end: date,
    reason_code: str,
) -> None:
    with pytest.raises(FinMindProbeError) as captured:
        _ = validate_probe_request(
            symbols=symbols,
            start_date=start,
            end_date=end,
            pacing_seconds=0,
        )
    assert captured.value.reason_code == reason_code


@final
class StaticTransport:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code: int = status_code
        self.payload: object = payload
        self.calls: int = 0

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> TransportResponse:
        _ = (url, headers, timeout)
        self.calls += 1
        return TransportResponse(
            status_code=self.status_code,
            headers={"Content-Type": "application/json"},
            body=json.dumps(self.payload).encode(),
        )


@pytest.mark.parametrize("status_code", [402, 403])
def test_quota_or_credential_denial_fails_closed_without_retry(
    status_code: int,
) -> None:
    transport = StaticTransport(status_code, {"status": status_code})
    client = FinMindClient(
        token="secret",
        http=JsonHttpClient(
            transport=transport,
            max_attempts=3,
            retry_backoff_seconds=0,
        ),
    )

    with pytest.raises(ProviderHttpError) as captured:
        _ = client.fetch_quota()

    assert captured.value.status_code == status_code
    assert transport.calls == 1
    assert "secret" not in str(captured.value)


def test_quota_schema_uses_only_documented_integer_fields() -> None:
    transport = StaticTransport(
        200,
        {"user_count": "10", "api_request_limit": 600},
    )
    client = FinMindClient(
        token="secret",
        http=JsonHttpClient(transport=transport, retry_backoff_seconds=0),
    )

    with pytest.raises(ProviderPayloadError) as captured:
        _ = client.fetch_quota()

    assert getattr(captured.value, "reason_code", None) == "FINMIND_QUOTA_PAYLOAD_INVALID"
