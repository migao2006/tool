from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.data.archive import HistoricalArchiveReadError, HistoricalParquetReader
from src.data.ingestion.historical_archive_contracts import HistoricalArchiveRequest
from src.data.ingestion.taiex_ohlc_archive import (
    build_taiex_ohlc_archive,
    build_taiex_ohlc_manifest,
)
from src.data.ingestion.taiex_ohlc_contracts import (
    NormalizedTaiexOhlcBatch,
    TaiexOhlcObservation,
)
from src.data.object_storage.r2_client import R2Client, R2Settings


OBSERVED_AT = datetime(2026, 7, 19, 5, tzinfo=timezone.utc)
PAYLOAD_HASH = "a" * 64
BUCKET = "alpha-lens-archive"


def _row(index: int, day: int, close: str) -> TaiexOhlcObservation:
    values = (f"2024/01/{day:02d}", "17,900", "18,000", "17,800", close)
    return TaiexOhlcObservation(
        source_row_index=index,
        source_row=values,
        landing_key=f"{index + 1:064x}",
        source_revision_hash=f"{index + 11:064x}",
        trade_date=date(2024, 1, day),
        open_index=Decimal("17900"),
        high_index=Decimal("18000"),
        low_index=Decimal("17800"),
        close_index=Decimal(close.replace(",", "")),
    )


def _batch() -> NormalizedTaiexOhlcBatch:
    return NormalizedTaiexOhlcBatch(
        requested_month=date(2024, 1, 1),
        response_date=date(2024, 1, 1),
        source_version="rwd.en.TAIEX.MI_5MINS_HIST.v1",
        source_url=(
            "https://www.twse.com.tw/rwd/en/TAIEX/MI_5MINS_HIST"
            "?date=20240101&response=json"
        ),
        source_payload_sha256=PAYLOAD_HASH,
        retrieved_at=OBSERVED_AT,
        rows=(_row(0, 2, "17,850"), _row(1, 3, "17,950")),
    )


class MemoryS3Client:
    def __init__(self, body: bytes, metadata: dict[str, str]) -> None:
        self.body = body
        self.metadata = metadata
        self.etag = '"taiex-etag"'

    def head_object(self, **kwargs: Any) -> dict[str, object]:
        return {
            "ContentLength": len(self.body),
            "ContentType": "application/vnd.apache.parquet",
            "Metadata": dict(self.metadata),
            "ETag": self.etag,
        }

    def get_object(self, **kwargs: Any) -> dict[str, object]:
        return {"Body": BytesIO(self.body)}

    def put_object(self, **kwargs: Any) -> dict[str, object]:
        raise AssertionError("archive reader must not write")

    def delete_object(self, **kwargs: Any) -> dict[str, object]:
        raise AssertionError("archive reader must not delete")


def _reader(store: MemoryS3Client) -> HistoricalParquetReader:
    settings = R2Settings(
        account_id="account123",
        access_key_id="access-key",
        secret_access_key="secret-key",
        bucket_name=BUCKET,
    )
    return HistoricalParquetReader(R2Client(settings, s3_client=store))


def test_taiex_uses_provider_scoped_key_and_shared_manifest_contract() -> None:
    batch = _batch()
    artifact = build_taiex_ohlc_archive(batch)
    expected_key = (
        "raw/v1/provider=twse/dataset=taiex_price_index_ohlc/"
        "scheduled_market=TWSE/asset_type=BENCHMARK/symbol=TAIEX/"
        "request_start=2024-01-01/request_end=2024-01-31/"
        f"payload_sha256={PAYLOAD_HASH}.parquet"
    )

    assert artifact.object_key == expected_key
    assert artifact.object_metadata()["provider-code"] == "TWSE"
    assert artifact.object_metadata()["source-dataset"] == "taiex_price_index_ohlc"
    manifest = build_taiex_ohlc_manifest(
        batch,
        artifact,
        bucket_name=BUCKET,
        object_etag='"taiex-etag"',
    )
    assert manifest.provider_code == "TWSE"
    assert manifest.min_trade_date == date(2024, 1, 2)
    assert manifest.max_trade_date == date(2024, 1, 3)
    assert manifest.system_status == "RESEARCH_ONLY"


def test_taiex_archive_roundtrips_through_r2_manifest_reader() -> None:
    batch = _batch()
    artifact = build_taiex_ohlc_archive(batch)
    store = MemoryS3Client(artifact.payload, artifact.object_metadata())
    manifest = build_taiex_ohlc_manifest(
        batch,
        artifact,
        bucket_name=BUCKET,
        object_etag=store.etag,
    )

    result = _reader(store).read(manifest)

    assert result.row_count == 2
    assert [row["trade_date"] for row in result.rows] == [
        date(2024, 1, 2),
        date(2024, 1, 3),
    ]
    assert result.rows[0]["benchmark_semantics"] == "PRICE_INDEX_NOT_TOTAL_RETURN"


def test_reader_rejects_taiex_ohlc_invariant_violation() -> None:
    batch = _batch()
    artifact = build_taiex_ohlc_archive(batch)
    table = pq.read_table(pa.BufferReader(artifact.payload))
    high_index = table.schema.get_field_index("high_index")
    table = table.set_column(
        high_index,
        table.schema.field(high_index),
        pa.array([Decimal("17000"), Decimal("18000")], type=pa.decimal128(18, 4)),
    )
    output = pa.BufferOutputStream()
    pq.write_table(table, output, compression="zstd")
    body = output.getvalue().to_pybytes()
    digest = sha256(body).hexdigest()
    metadata = artifact.object_metadata()
    metadata["content-sha256"] = digest
    metadata["byte-size"] = str(len(body))
    store = MemoryS3Client(body, metadata)
    manifest = build_taiex_ohlc_manifest(
        batch,
        artifact,
        bucket_name=BUCKET,
        object_etag=store.etag,
    )
    manifest = replace(manifest, parquet_sha256=digest, byte_size=len(body))

    with pytest.raises(HistoricalArchiveReadError) as captured:
        _reader(store).read(manifest)

    assert captured.value.reason_code == "TAIEX_OHLC_ARCHIVE_INVALID"


@pytest.mark.parametrize(
    ("provider", "dataset"),
    (("TWSE", "daily_bars"), ("FINMIND", "taiex_price_index_ohlc")),
)
def test_archive_request_rejects_cross_provider_dataset_pairs(
    provider: str,
    dataset: str,
) -> None:
    with pytest.raises(ValueError, match="allowed archive pair"):
        HistoricalArchiveRequest(
            provider_code=provider,
            source_dataset=dataset,
            scheduled_market="TWSE",
            asset_type="BENCHMARK",
            source_symbol="TAIEX",
            requested_start_date=date(2024, 1, 1),
            requested_end_date=date(2024, 1, 31),
            source_payload_sha256=PAYLOAD_HASH,
            retrieved_at=OBSERVED_AT,
        )
