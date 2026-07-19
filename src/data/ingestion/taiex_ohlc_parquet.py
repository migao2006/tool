"""Serialize strict TWSE TAIEX price-index OHLC rows as ZSTD Parquet."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from hashlib import sha256
from typing import Any

from src.data.providers.twse import TAIEX_MONTHLY_OHLC_DATASET

from .contracts import IngestionError
from .historical_parquet_serializer import canonical_json
from .taiex_ohlc_contracts import (
    TAIEX_OHLC_COMPRESSION,
    TAIEX_OHLC_SCHEMA_VERSION,
    NormalizedTaiexOhlcBatch,
    TaiexOhlcParquetArtifact,
)


def _pyarrow_modules() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ModuleNotFoundError as error:
        raise IngestionError(
            "PARQUET_DEPENDENCY_MISSING",
            "pyarrow is required to serialize TAIEX OHLC history",
        ) from error
    return pa, pq


def taiex_ohlc_schema() -> Any:
    pa, _ = _pyarrow_modules()
    return pa.schema(
        (
            pa.field("archive_schema_version", pa.string(), nullable=False),
            pa.field("source_code", pa.string(), nullable=False),
            pa.field("source_dataset", pa.string(), nullable=False),
            pa.field("source_version", pa.string(), nullable=False),
            pa.field("source_payload_sha256", pa.string(), nullable=False),
            pa.field("source_url", pa.string(), nullable=False),
            pa.field("source_row_index", pa.int64(), nullable=False),
            pa.field("source_row", pa.large_string(), nullable=False),
            pa.field("landing_key", pa.string(), nullable=False),
            pa.field("source_revision_hash", pa.string(), nullable=False),
            pa.field("retrieved_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("available_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("available_at_basis", pa.string(), nullable=False),
            pa.field("point_in_time_status", pa.string(), nullable=False),
            pa.field("usage_scope", pa.string(), nullable=False),
            pa.field("system_status", pa.string(), nullable=False),
            pa.field("reason_codes", pa.large_string(), nullable=False),
            pa.field("requested_month", pa.date32(), nullable=False),
            pa.field("response_date", pa.date32(), nullable=False),
            pa.field("trade_date", pa.date32(), nullable=False),
            pa.field("open_index", pa.decimal128(18, 4), nullable=False),
            pa.field("high_index", pa.decimal128(18, 4), nullable=False),
            pa.field("low_index", pa.decimal128(18, 4), nullable=False),
            pa.field("close_index", pa.decimal128(18, 4), nullable=False),
            pa.field("benchmark_semantics", pa.string(), nullable=False),
        ),
        metadata={
            b"archive.schema_version": TAIEX_OHLC_SCHEMA_VERSION.encode(),
            b"archive.source_dataset": TAIEX_MONTHLY_OHLC_DATASET.encode(),
            b"archive.compression": TAIEX_OHLC_COMPRESSION.lower().encode(),
            b"source_row.encoding": b"canonical-json-v1",
            b"reason_codes.encoding": b"canonical-json-v1",
            b"available_at.semantics": b"first-project-retrieval-only",
            b"benchmark.semantics": b"price-index-not-total-return",
            b"point_in_time.status": b"UNVERIFIED",
            b"usage.scope": b"RAW_LANDING_ONLY",
            b"system.status": b"RESEARCH_ONLY",
        },
    )


def serialize_taiex_ohlc_parquet(
    batch: NormalizedTaiexOhlcBatch,
) -> TaiexOhlcParquetArtifact:
    pa, pq = _pyarrow_modules()
    reason_codes = canonical_json(list(batch.reason_codes), field_name="reason_codes")
    archived = [
        {
            "archive_schema_version": TAIEX_OHLC_SCHEMA_VERSION,
            "source_code": "TWSE",
            "source_dataset": TAIEX_MONTHLY_OHLC_DATASET,
            "source_version": batch.source_version,
            "source_payload_sha256": batch.source_payload_sha256,
            "source_url": batch.source_url,
            "source_row_index": row.source_row_index,
            "source_row": canonical_json(list(row.source_row), field_name="source_row"),
            "landing_key": row.landing_key,
            "source_revision_hash": row.source_revision_hash,
            "retrieved_at": batch.retrieved_at,
            "available_at": batch.retrieved_at,
            "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
            "point_in_time_status": batch.point_in_time_status,
            "usage_scope": batch.usage_scope,
            "system_status": batch.system_status,
            "reason_codes": reason_codes,
            "requested_month": batch.requested_month,
            "response_date": batch.response_date,
            "trade_date": row.trade_date,
            "open_index": row.open_index,
            "high_index": row.high_index,
            "low_index": row.low_index,
            "close_index": row.close_index,
            "benchmark_semantics": "PRICE_INDEX_NOT_TOTAL_RETURN",
        }
        for row in sorted(batch.rows, key=lambda value: value.trade_date)
    ]
    schema = taiex_ohlc_schema().with_metadata(
        {
            **(taiex_ohlc_schema().metadata or {}),
            b"archive.requested_month": batch.requested_month.strftime(
                "%Y-%m"
            ).encode(),
            b"archive.source_payload_sha256": batch.source_payload_sha256.encode(),
            b"archive.retrieved_at": batch.retrieved_at.isoformat().encode(),
            b"source.version": batch.source_version.encode(),
            b"source.url": batch.source_url.encode(),
            b"reason_codes": reason_codes.encode(),
        }
    )
    table = pa.Table.from_pylist(archived, schema=schema)
    output = pa.BufferOutputStream()
    pq.write_table(
        table,
        output,
        compression="zstd",
        compression_level=9,
        version="2.6",
        data_page_version="2.0",
        write_statistics=True,
        coerce_timestamps="us",
        allow_truncated_timestamps=False,
    )
    payload = output.getvalue().to_pybytes()
    return TaiexOhlcParquetArtifact(
        payload=payload,
        content_sha256=sha256(payload).hexdigest(),
        byte_size=len(payload),
        row_count=len(archived),
        requested_month=batch.requested_month,
        source_payload_sha256=batch.source_payload_sha256,
    )
