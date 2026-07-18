from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from io import BytesIO
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.data.archive import (
    HistoricalArchiveReadError,
    HistoricalParquetReader,
)
from src.data.ingestion.historical_archive_contracts import HistoricalArchiveRequest
from src.data.ingestion.historical_parquet_serializer import (
    serialize_historical_parquet,
)
from src.data.object_storage.r2_client import R2Client, R2Settings


OBSERVED_AT = datetime(2026, 7, 19, 4, tzinfo=timezone.utc)
START_DATE = date(2020, 1, 1)
END_DATE = date(2020, 1, 31)
SOURCE_PAYLOAD_HASH = "c" * 64
BUCKET = "alpha-lens-archive"


class MemoryS3Client:
    def __init__(self) -> None:
        self.body = b""
        self.content_type = "application/vnd.apache.parquet"
        self.metadata: dict[str, str] = {}
        self.etag = '"archive-etag"'

    def head_object(self, **kwargs: Any) -> dict[str, object]:
        return {
            "ContentLength": len(self.body),
            "ContentType": self.content_type,
            "Metadata": dict(self.metadata),
            "ETag": self.etag,
        }

    def get_object(self, **kwargs: Any) -> dict[str, object]:
        return {"Body": BytesIO(self.body)}

    def put_object(self, **kwargs: Any) -> dict[str, object]:
        raise AssertionError("reader must not write R2 objects")

    def delete_object(self, **kwargs: Any) -> dict[str, object]:
        raise AssertionError("reader must not delete R2 objects")


def _request() -> HistoricalArchiveRequest:
    return HistoricalArchiveRequest(
        scheduled_market="TWSE",
        asset_type="COMMON_STOCK",
        source_symbol="2330",
        requested_start_date=START_DATE,
        requested_end_date=END_DATE,
        source_payload_sha256=SOURCE_PAYLOAD_HASH,
        retrieved_at=OBSERVED_AT,
    )


def _row(index: int) -> dict[str, object]:
    trade_date = date(2020, 1, 2 + index)
    return {
        "landing_key": f"{index + 1:064x}",
        "source_code": "FINMIND",
        "source_dataset": "daily_bars",
        "source_symbol": "2330",
        "source_market_claim": None,
        "source_market_basis": "UNAVAILABLE",
        "source_version": "api.v4",
        "source_revision_hash": f"{index + 11:064x}",
        "source_payload_hash": SOURCE_PAYLOAD_HASH,
        "source_url": "https://api.finmindtrade.com/api/v4/data",
        "source_row_index": index,
        "source_row": {"stock_id": "2330", "date": trade_date.isoformat()},
        "first_observed_at": OBSERVED_AT.isoformat(),
        "available_at": OBSERVED_AT.isoformat(),
        "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
        "identity_resolution_status": "UNRESOLVED",
        "point_in_time_status": "UNVERIFIED",
        "usage_scope": "RAW_LANDING_ONLY",
        "system_status": "RESEARCH_ONLY",
        "reason_codes": ["POINT_IN_TIME_UNVERIFIED", "RAW_LANDING_ONLY"],
        "source_trade_date": trade_date.isoformat(),
        "trade_date": trade_date.isoformat(),
        "parse_status": "PARSED",
        "open_price": "100",
        "high_price": "102",
        "low_price": "99",
        "close_price": "101",
        "trading_volume": "1000000",
        "trading_value": "101000000",
        "trade_count": 1000,
    }


def _archive() -> tuple[MemoryS3Client, dict[str, object]]:
    artifact = serialize_historical_parquet([_row(0), _row(1)], request=_request())
    store = MemoryS3Client()
    store.body = artifact.payload
    store.metadata = artifact.object_metadata()
    archive_key = sha256(f"{BUCKET}\0{artifact.object_key}".encode()).hexdigest()
    manifest: dict[str, object] = {
        "archive_key": archive_key,
        "storage_provider": "CLOUDFLARE_R2",
        "bucket_name": BUCKET,
        "object_key": artifact.object_key,
        "object_etag": store.etag,
        "schema_version": artifact.schema_version,
        "provider_code": "FINMIND",
        "source_dataset": "daily_bars",
        "source_version": "api.v4",
        "source_symbol": "2330",
        "scheduled_market": "TWSE",
        "asset_type": "COMMON_STOCK",
        "requested_start_date": START_DATE.isoformat(),
        "requested_end_date": END_DATE.isoformat(),
        "min_trade_date": "2020-01-02",
        "max_trade_date": "2020-01-03",
        "source_payload_hash": SOURCE_PAYLOAD_HASH,
        "parquet_sha256": artifact.content_sha256,
        "byte_size": artifact.byte_size,
        "row_count": 2,
        "parsed_row_count": 2,
        "quarantined_row_count": 0,
        "first_observed_at": OBSERVED_AT.isoformat(),
        "point_in_time_status": "UNVERIFIED",
        "usage_scope": "RAW_LANDING_ONLY",
        "system_status": "RESEARCH_ONLY",
        "reason_codes": ["POINT_IN_TIME_UNVERIFIED", "RAW_LANDING_ONLY"],
    }
    return store, manifest


def _reader(store: MemoryS3Client) -> HistoricalParquetReader:
    settings = R2Settings(
        account_id="account123",
        access_key_id="access-key",
        secret_access_key="secret-key",
        bucket_name=BUCKET,
    )
    return HistoricalParquetReader(R2Client(settings, s3_client=store))


def _replace_payload(
    store: MemoryS3Client,
    manifest: dict[str, object],
    table: pa.Table,
) -> None:
    output = pa.BufferOutputStream()
    pq.write_table(table, output, compression="zstd")
    store.body = output.getvalue().to_pybytes()
    digest = sha256(store.body).hexdigest()
    store.metadata["content-sha256"] = digest
    store.metadata["byte-size"] = str(len(store.body))
    manifest["parquet_sha256"] = digest
    manifest["byte_size"] = len(store.body)


def test_reader_releases_rows_only_after_complete_integrity_verification() -> None:
    store, manifest = _archive()

    result = _reader(store).read(manifest)

    assert result.row_count == 2
    assert result.byte_size == len(store.body)
    assert result.content_sha256 == sha256(store.body).hexdigest()
    assert [row["trade_date"] for row in result.rows] == [
        date(2020, 1, 2),
        date(2020, 1, 3),
    ]
    with pytest.raises(TypeError):
        result.rows[0]["source_symbol"] = "2317"  # type: ignore[index]


def test_reader_fails_closed_on_r2_size_or_payload_digest_mismatch() -> None:
    store, manifest = _archive()
    manifest["byte_size"] = int(manifest["byte_size"]) + 1

    with pytest.raises(HistoricalArchiveReadError) as size_error:
        _reader(store).read(manifest)
    assert size_error.value.reason_code == "HISTORICAL_ARCHIVE_R2_METADATA_MISMATCH"

    store, manifest = _archive()
    store.body = bytes([store.body[0] ^ 1]) + store.body[1:]
    with pytest.raises(HistoricalArchiveReadError) as digest_error:
        _reader(store).read(manifest)
    assert digest_error.value.reason_code == "HISTORICAL_ARCHIVE_CONTENT_MISMATCH"


def test_reader_rejects_wrong_row_count_and_missing_fixed_schema_metadata() -> None:
    store, manifest = _archive()
    manifest["row_count"] = 3
    manifest["parsed_row_count"] = 3
    store.metadata["row-count"] = "3"

    with pytest.raises(HistoricalArchiveReadError) as count_error:
        _reader(store).read(manifest)
    assert count_error.value.reason_code == "HISTORICAL_ARCHIVE_ROW_COUNT_MISMATCH"

    store, manifest = _archive()
    table = pq.read_table(pa.BufferReader(store.body)).replace_schema_metadata({})
    _replace_payload(store, manifest, table)
    with pytest.raises(HistoricalArchiveReadError) as metadata_error:
        _reader(store).read(manifest)
    assert (
        metadata_error.value.reason_code
        == "HISTORICAL_ARCHIVE_SCHEMA_METADATA_MISMATCH"
    )


@pytest.mark.parametrize(
    ("column", "value", "reason_code"),
    [
        ("source_symbol", "2317", "HISTORICAL_ARCHIVE_SYMBOL_MISMATCH"),
        ("trade_date", date(2019, 12, 31), "HISTORICAL_ARCHIVE_DATE_MISMATCH"),
    ],
)
def test_reader_rejects_rows_for_another_symbol_or_date_range(
    column: str,
    value: object,
    reason_code: str,
) -> None:
    store, manifest = _archive()
    table = pq.read_table(pa.BufferReader(store.body))
    index = table.schema.get_field_index(column)
    table = table.set_column(index, column, pa.array([value, table[column][1].as_py()]))
    _replace_payload(store, manifest, table)

    with pytest.raises(HistoricalArchiveReadError) as captured:
        _reader(store).read(manifest)
    assert captured.value.reason_code == reason_code


def test_reader_rejects_non_deterministic_row_order() -> None:
    store, manifest = _archive()
    table = pq.read_table(pa.BufferReader(store.body)).take(pa.array([1, 0]))
    _replace_payload(store, manifest, table)

    with pytest.raises(HistoricalArchiveReadError) as captured:
        _reader(store).read(manifest)
    assert captured.value.reason_code == "HISTORICAL_ARCHIVE_SORT_ORDER_INVALID"


def test_reader_rejects_manifest_for_another_bucket_before_r2_access() -> None:
    store, manifest = _archive()
    manifest["bucket_name"] = "another-private-bucket"
    manifest["archive_key"] = sha256(
        f"another-private-bucket\0{manifest['object_key']}".encode()
    ).hexdigest()

    with pytest.raises(HistoricalArchiveReadError) as captured:
        _reader(store).read(manifest)
    assert captured.value.reason_code == "HISTORICAL_ARCHIVE_BUCKET_MISMATCH"
