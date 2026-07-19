from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
import json
from urllib.parse import parse_qs, urlsplit

import pyarrow.parquet as pq
import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.taiex_ohlc_contracts import TAIEX_OHLC_FIELDS
from src.data.ingestion.taiex_ohlc_normalizer import normalize_taiex_monthly_ohlc
from src.data.ingestion.taiex_ohlc_parquet import serialize_taiex_ohlc_parquet
from src.data.providers.contracts import ProviderPayload
from src.data.providers.http import JsonHttpClient, TransportResponse
from src.data.providers.twse import (
    TAIEX_MONTHLY_OHLC_DATASET,
    TAIEX_MONTHLY_OHLC_SOURCE_VERSION,
    TwseClient,
)


RETRIEVED_AT = datetime(2026, 7, 19, 5, tzinfo=timezone.utc)


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
        "stat": "OK",
        "date": "20240101",
        "title": "2024/01 TAIEX Total Index Historical Data",
        "fields": list(TAIEX_OHLC_FIELDS),
        "data": [
            ["2024/01/02", "17,939.79", "17,956.74", "17,784.97", "17,853.76"],
            ["2024/01/03", "17,860.13", "17,868.69", "17,639.39", "17,643.69"],
        ],
    }


def _payload(body: object | None = None) -> ProviderPayload:
    raw = _body() if body is None else body
    encoded = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    return ProviderPayload(
        provider="TWSE",
        dataset=TAIEX_MONTHLY_OHLC_DATASET,
        source_version=TAIEX_MONTHLY_OHLC_SOURCE_VERSION,
        source_url=(
            "https://www.twse.com.tw/rwd/en/TAIEX/MI_5MINS_HIST"
            "?date=20240101&response=json"
        ),
        retrieved_at=RETRIEVED_AT,
        payload_sha256=sha256(encoded).hexdigest(),
        payload=raw,
        request_metadata={
            "requested_month": "2024-01",
            "request_date": "20240101",
            "calendar": "GREGORIAN",
            "language": "en",
            "available_at_policy": "first_project_retrieval_only",
        },
    )


def test_provider_uses_official_english_rwd_endpoint_and_gregorian_month() -> None:
    transport = FakeTransport(_body())
    client = TwseClient(
        http=JsonHttpClient(transport=transport, retry_backoff_seconds=0)
    )

    payload = client.fetch_taiex_monthly_ohlc(date(2024, 1, 31))

    parsed = urlsplit(transport.calls[0])
    assert parsed.path == "/rwd/en/TAIEX/MI_5MINS_HIST"
    assert parse_qs(parsed.query) == {"date": ["20240101"], "response": ["json"]}
    assert payload.dataset == TAIEX_MONTHLY_OHLC_DATASET
    assert payload.source_version == TAIEX_MONTHLY_OHLC_SOURCE_VERSION
    assert payload.request_metadata["requested_month"] == "2024-01"
    assert payload.request_metadata["calendar"] == "GREGORIAN"
    assert payload.request_metadata["language"] == "en"


def test_provider_rejects_non_gregorian_month_input() -> None:
    client = TwseClient(http=JsonHttpClient(transport=FakeTransport(_body())))
    with pytest.raises(ValueError, match="Gregorian"):
        client.fetch_taiex_monthly_ohlc("113/01")


def test_normalizer_preserves_strict_ohlc_and_research_provenance() -> None:
    batch = normalize_taiex_monthly_ohlc(_payload())

    assert batch.requested_month == date(2024, 1, 1)
    assert batch.response_date == date(2024, 1, 1)
    assert len(batch.rows) == 2
    first = batch.rows[0]
    assert first.trade_date == date(2024, 1, 2)
    assert first.open_index == Decimal("17939.79")
    assert first.high_index == Decimal("17956.74")
    assert first.low_index == Decimal("17784.97")
    assert first.close_index == Decimal("17853.76")
    assert len(first.landing_key) == 64
    assert len(first.source_revision_hash) == 64
    assert batch.point_in_time_status == "UNVERIFIED"
    assert batch.usage_scope == "RAW_LANDING_ONLY"
    assert batch.system_status == "RESEARCH_ONLY"
    assert "PRICE_INDEX_NOT_TOTAL_RETURN" in batch.reason_codes
    assert batch.retrieved_at == RETRIEVED_AT


def test_normalizer_rejects_non_official_source_url() -> None:
    payload = replace(_payload(), source_url="https://example.com/taiex")

    with pytest.raises(IngestionError) as captured:
        normalize_taiex_monthly_ohlc(payload)

    assert captured.value.reason_code == "TAIEX_OHLC_SOURCE_URL_INVALID"


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        (lambda body: body.update(stat="NO_DATA"), "TAIEX_OHLC_STAT_NOT_OK"),
        (
            lambda body: body.update(fields=["Date", "Open"]),
            "TAIEX_OHLC_FIELDS_MISMATCH",
        ),
        (
            lambda body: body.update(date="20240201"),
            "TAIEX_OHLC_RESPONSE_MONTH_MISMATCH",
        ),
        (
            lambda body: body["data"].append(deepcopy(body["data"][0])),
            "TAIEX_OHLC_DUPLICATE_TRADE_DATE",
        ),
        (
            lambda body: body["data"][0].__setitem__(1, "NaN"),
            "TAIEX_OHLC_VALUE_INVALID",
        ),
        (
            lambda body: body["data"][0].__setitem__(2, "17,000"),
            "TAIEX_OHLC_HIGH_INVARIANT_FAILED",
        ),
        (
            lambda body: body["data"][0].__setitem__(3, "17,900"),
            "TAIEX_OHLC_LOW_INVARIANT_FAILED",
        ),
        (
            lambda body: body["data"][0].__setitem__(0, "2024/02/01"),
            "TAIEX_OHLC_TRADE_DATE_OUTSIDE_MONTH",
        ),
    ],
)
def test_normalizer_fails_closed_on_contract_violations(
    mutation, reason_code: str
) -> None:
    body = _body()
    mutation(body)

    with pytest.raises(IngestionError) as captured:
        normalize_taiex_monthly_ohlc(_payload(body))

    assert captured.value.reason_code == reason_code


def test_parquet_is_zstd_and_retains_provenance_and_research_semantics() -> None:
    batch = normalize_taiex_monthly_ohlc(_payload())

    artifact = serialize_taiex_ohlc_parquet(batch)

    parquet = pq.ParquetFile(BytesIO(artifact.payload))
    table = parquet.read()
    metadata = table.schema.metadata or {}
    assert artifact.schema_version == "twse_taiex_price_index_ohlc.v1"
    assert artifact.compression == "ZSTD"
    assert parquet.metadata.row_group(0).column(0).compression == "ZSTD"
    assert (
        metadata[b"archive.source_payload_sha256"]
        == batch.source_payload_sha256.encode()
    )
    assert metadata[b"archive.requested_month"] == b"2024-01"
    assert metadata[b"available_at.semantics"] == b"first-project-retrieval-only"
    assert metadata[b"benchmark.semantics"] == b"price-index-not-total-return"
    assert metadata[b"usage.scope"] == b"RAW_LANDING_ONLY"
    assert metadata[b"system.status"] == b"RESEARCH_ONLY"
    assert table.column("trade_date").to_pylist() == [
        date(2024, 1, 2),
        date(2024, 1, 3),
    ]
    assert table.column("open_index").to_pylist()[0] == Decimal("17939.7900")
    assert table.column("source_url").to_pylist() == [
        batch.source_url,
        batch.source_url,
    ]
    assert table.column("source_payload_sha256").to_pylist() == [
        batch.source_payload_sha256,
        batch.source_payload_sha256,
    ]
    assert table.column("landing_key").to_pylist()[0] == batch.rows[0].landing_key
    assert (
        table.column("source_revision_hash").to_pylist()[0]
        == batch.rows[0].source_revision_hash
    )
    assert table.column("usage_scope").to_pylist() == ["RAW_LANDING_ONLY"] * 2
    assert table.column("system_status").to_pylist() == ["RESEARCH_ONLY"] * 2
