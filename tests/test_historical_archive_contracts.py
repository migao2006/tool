from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256

import pytest

from src.data.ingestion.historical_archive_contracts import (
    HISTORICAL_ARCHIVE_CONTENT_TYPE,
    HistoricalArchiveArtifact,
    HistoricalArchiveRequest,
)


PAYLOAD_DIGEST = "a" * 64


def archive_request(**updates: object) -> HistoricalArchiveRequest:
    values: dict[str, object] = {
        "scheduled_market": "twse",
        "asset_type": "common_stock",
        "source_symbol": "2330",
        "requested_start_date": date(2020, 1, 1),
        "requested_end_date": date(2026, 7, 18),
        "source_payload_sha256": PAYLOAD_DIGEST.upper(),
        "retrieved_at": datetime(
            2026,
            7,
            18,
            14,
            tzinfo=timezone(timedelta(hours=8)),
        ),
    }
    values.update(updates)
    return HistoricalArchiveRequest(**values)  # pyright: ignore[reportArgumentType]


def test_archive_request_canonicalizes_safe_identity_fields() -> None:
    request = archive_request()

    assert request.scheduled_market == "TWSE"
    assert request.asset_type == "COMMON_STOCK"
    assert request.source_payload_sha256 == PAYLOAD_DIGEST
    assert request.retrieved_at == datetime(2026, 7, 18, 6, tzinfo=timezone.utc)


@pytest.mark.parametrize("source_symbol", ("..", "../2330", "2330/evil", "2330\\evil"))
def test_archive_request_rejects_traversal_symbols(source_symbol: str) -> None:
    with pytest.raises(ValueError, match="path"):
        archive_request(source_symbol=source_symbol)


def test_archive_request_rejects_invalid_market_dates_and_digest() -> None:
    with pytest.raises(ValueError, match="scheduled_market"):
        archive_request(scheduled_market="NYSE")
    with pytest.raises(ValueError, match="must not be after"):
        archive_request(
            requested_start_date=date(2026, 7, 19),
            requested_end_date=date(2026, 7, 18),
        )
    with pytest.raises(ValueError, match="SHA-256"):
        archive_request(source_payload_sha256="not-a-digest")
    with pytest.raises(ValueError, match="timezone-aware"):
        archive_request(retrieved_at=datetime(2026, 7, 18, 6))


@pytest.mark.parametrize(
    ("provider_code", "source_dataset"),
    (
        ("TPEX", "daily_bars"),
        ("TPEX", "taiex_price_index_ohlc"),
        ("TWSE", "tpex_price_index_ohlc"),
        ("FINMIND", "tpex_price_index_ohlc"),
    ),
)
def test_archive_request_rejects_cross_provider_dataset_pairs(
    provider_code: str,
    source_dataset: str,
) -> None:
    with pytest.raises(ValueError, match="allowed archive pair"):
        archive_request(
            provider_code=provider_code,
            source_dataset=source_dataset,
        )


def test_archive_request_accepts_the_tpex_benchmark_tuple() -> None:
    request = archive_request(
        provider_code="TPEX",
        source_dataset="tpex_price_index_ohlc",
        scheduled_market="TPEX",
        asset_type="BENCHMARK",
        source_symbol="TPEX_INDEX",
    )

    assert request.provider_code == "TPEX"
    assert request.source_dataset == "tpex_price_index_ohlc"
    assert request.scheduled_market == "TPEX"
    assert request.asset_type == "BENCHMARK"


@pytest.mark.parametrize(
    ("scheduled_market", "asset_type"),
    (("TWSE", "BENCHMARK"), ("TPEX", "COMMON_STOCK")),
)
def test_archive_request_rejects_invalid_tpex_benchmark_scope(
    scheduled_market: str,
    asset_type: str,
) -> None:
    with pytest.raises(ValueError, match="TPEX benchmark scope"):
        archive_request(
            provider_code="TPEX",
            source_dataset="tpex_price_index_ohlc",
            scheduled_market=scheduled_market,
            asset_type=asset_type,
            source_symbol="TPEX_INDEX",
        )


def test_artifact_validates_integrity_and_exposes_r2_metadata() -> None:
    request = archive_request()
    payload = b"PAR1-test"
    artifact = HistoricalArchiveArtifact(
        request=request,
        object_key="historical-daily-bars/test.parquet",
        payload=payload,
        content_sha256=sha256(payload).hexdigest(),
        byte_size=len(payload),
        row_count=2,
    )

    assert artifact.content_type == HISTORICAL_ARCHIVE_CONTENT_TYPE
    assert artifact.object_metadata() == {
        "content-sha256": sha256(payload).hexdigest(),
        "byte-size": str(len(payload)),
        "row-count": "2",
        "schema-version": "historical_daily_bars.v1",
        "compression": "zstd",
        "scheduled-market": "TWSE",
        "asset-type": "COMMON_STOCK",
        "source-payload-sha256": PAYLOAD_DIGEST,
        "retrieved-at": "2026-07-18T06:00:00+00:00",
    }

    with pytest.raises(ValueError, match="content_sha256"):
        replace(artifact, content_sha256="0" * 64)
