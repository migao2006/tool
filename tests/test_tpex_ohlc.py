from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.tpex_ohlc_contracts import TPEX_OHLC_FIELDS
from src.data.ingestion.tpex_ohlc_normalizer import normalize_tpex_monthly_ohlc
from src.data.providers.contracts import ProviderPayload
from src.data.providers.http import JsonHttpClient, TransportResponse
from src.data.providers.tpex import (
    TPEX_MONTHLY_OHLC_DATASET,
    TPEX_MONTHLY_OHLC_SOURCE_VERSION,
    TpexClient,
)


RETRIEVED_AT = datetime(2026, 7, 20, 5, tzinfo=timezone.utc)


class FakeTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def get(self, url: str, *, headers, timeout: float) -> TransportResponse:
        _ = (headers, timeout)
        self.calls.append(url)
        body = json.dumps(self.payload).encode()
        return TransportResponse(200, {"Content-Type": "application/json"}, body)


def _body() -> dict[str, object]:
    return {
        "date": "20240101",
        "tables": [
            {
                "title": "Historical Data of TPEx Index",
                "date": "2024/01",
                "totalCount": 2,
                "fields": list(TPEX_OHLC_FIELDS),
                "data": [
                    ["2024/01/02", "234.13", "234.96", "232.69", "233.23", "-0.78"],
                    ["2024/01/03", "232.94", "232.94", "230.69", "231.05", "-2.18"],
                ],
                "summary": [],
                "notes": [],
            }
        ],
        "stat": "ok",
    }


def _payload(body: object | None = None) -> ProviderPayload:
    raw = _body() if body is None else body
    encoded = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    return ProviderPayload(
        provider="TPEX",
        dataset=TPEX_MONTHLY_OHLC_DATASET,
        source_version=TPEX_MONTHLY_OHLC_SOURCE_VERSION,
        source_url=(
            "https://www.tpex.org.tw/www/en-us/indexInfo/inx"
            "?date=2024%2F01%2F01&response=json"
        ),
        retrieved_at=RETRIEVED_AT,
        payload_sha256=sha256(encoded).hexdigest(),
        payload=raw,
        request_metadata={
            "requested_month": "2024-01",
            "request_date": "2024/01/01",
            "calendar": "GREGORIAN",
            "language": "en",
            "available_at_policy": "first_project_retrieval_only",
        },
    )


def test_provider_uses_official_english_endpoint_and_gregorian_month() -> None:
    transport = FakeTransport(_body())
    client = TpexClient(
        http=JsonHttpClient(transport=transport, retry_backoff_seconds=0)
    )

    payload = client.fetch_monthly_index_ohlc(date(2024, 1, 31))

    parsed = urlsplit(transport.calls[0])
    assert parsed.scheme == "https"
    assert parsed.hostname == "www.tpex.org.tw"
    assert parsed.path == "/www/en-us/indexInfo/inx"
    assert parse_qs(parsed.query) == {
        "date": ["2024/01/01"],
        "response": ["json"],
    }
    assert payload.dataset == TPEX_MONTHLY_OHLC_DATASET
    assert payload.source_version == TPEX_MONTHLY_OHLC_SOURCE_VERSION
    assert payload.request_metadata["requested_month"] == "2024-01"
    assert payload.request_metadata["calendar"] == "GREGORIAN"
    assert payload.request_metadata["language"] == "en"


def test_provider_rejects_non_gregorian_month_input() -> None:
    client = TpexClient(http=JsonHttpClient(transport=FakeTransport(_body())))

    with pytest.raises(ValueError, match="Gregorian"):
        client.fetch_monthly_index_ohlc("113/01")


def test_normalizer_preserves_ohlc_hashes_and_research_provenance() -> None:
    batch = normalize_tpex_monthly_ohlc(_payload())

    assert batch.requested_month == date(2024, 1, 1)
    assert batch.response_date == date(2024, 1, 1)
    assert batch.retrieved_at == RETRIEVED_AT
    assert batch.available_at == batch.retrieved_at
    assert batch.point_in_time_status == "UNVERIFIED"
    assert batch.usage_scope == "RAW_LANDING_ONLY"
    assert batch.system_status == "RESEARCH_ONLY"
    assert "PRICE_INDEX_NOT_TOTAL_RETURN" in batch.reason_codes
    first = batch.rows[0]
    assert first.trade_date == date(2024, 1, 2)
    assert first.open_index == Decimal("234.13")
    assert first.high_index == Decimal("234.96")
    assert first.low_index == Decimal("232.69")
    assert first.close_index == Decimal("233.23")
    assert len(first.landing_key) == 64
    assert len(first.source_revision_hash) == 64
    assert (
        first.source_revision_hash
        == normalize_tpex_monthly_ohlc(_payload()).rows[0].source_revision_hash
    )


def test_normalizer_rejects_non_official_source_url() -> None:
    payload = replace(_payload(), source_url="https://example.com/tpex")

    with pytest.raises(IngestionError) as captured:
        normalize_tpex_monthly_ohlc(payload)

    assert captured.value.reason_code == "TPEX_OHLC_SOURCE_URL_INVALID"


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        (lambda body: body.update(stat="OK"), "TPEX_OHLC_STAT_NOT_OK"),
        (
            lambda body: body["tables"][0].update(fields=["Date", "Open"]),
            "TPEX_OHLC_FIELDS_MISMATCH",
        ),
        (
            lambda body: body.update(date="20240201"),
            "TPEX_OHLC_RESPONSE_MONTH_MISMATCH",
        ),
        (
            lambda body: body["tables"][0].update(date="2024/02"),
            "TPEX_OHLC_TABLE_MONTH_MISMATCH",
        ),
        (
            lambda body: body["tables"][0]["data"].append(
                deepcopy(body["tables"][0]["data"][0])
            ),
            "TPEX_OHLC_TOTAL_COUNT_MISMATCH",
        ),
        (
            lambda body: body["tables"][0]["data"].reverse(),
            "TPEX_OHLC_TRADE_DATES_NOT_ASCENDING",
        ),
        (
            lambda body: body["tables"][0]["data"][0].__setitem__(1, "NaN"),
            "TPEX_OHLC_VALUE_INVALID",
        ),
        (
            lambda body: body["tables"][0]["data"][0].__setitem__(2, "230"),
            "TPEX_OHLC_HIGH_INVARIANT_FAILED",
        ),
        (
            lambda body: body["tables"][0]["data"][0].__setitem__(3, "234.50"),
            "TPEX_OHLC_LOW_INVARIANT_FAILED",
        ),
        (
            lambda body: body["tables"][0]["data"][0].__setitem__(0, "2024/02/01"),
            "TPEX_OHLC_TRADE_DATE_OUTSIDE_MONTH",
        ),
    ],
)
def test_normalizer_fails_closed_on_contract_violations(
    mutation, reason_code: str
) -> None:
    body = _body()
    mutation(body)

    with pytest.raises(IngestionError) as captured:
        normalize_tpex_monthly_ohlc(_payload(body))

    assert captured.value.reason_code == reason_code
