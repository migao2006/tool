"""Serialize official TWSE TAIEX OHLC into the shared archive contract."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from calendar import monthrange
from hashlib import sha256
from typing import Any

from src.data.providers.twse import TAIEX_MONTHLY_OHLC_DATASET

from .contracts import IngestionError
from .historical_archive_contracts import (
    HISTORICAL_ARCHIVE_COMPRESSION,
    HISTORICAL_ARCHIVE_SCHEMA_VERSIONS,
    HistoricalArchiveArtifact,
    HistoricalArchiveRequest,
)
from .historical_object_key import build_historical_object_key
from .historical_parquet_serializer import canonical_json
from .taiex_ohlc_contracts import (
    TAIEX_OHLC_SCHEMA_VERSION,
    TAIEX_OHLC_SYMBOL,
    NormalizedTaiexOhlcBatch,
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
            pa.field("scheduled_market", pa.string(), nullable=False),
            pa.field("scheduled_asset_type", pa.string(), nullable=False),
            pa.field("requested_start_date", pa.date32(), nullable=False),
            pa.field("requested_end_date", pa.date32(), nullable=False),
            pa.field("source_code", pa.string(), nullable=False),
            pa.field("source_dataset", pa.string(), nullable=False),
            pa.field("source_symbol", pa.string(), nullable=False),
            pa.field("source_version", pa.string(), nullable=False),
            pa.field("source_payload_hash", pa.string(), nullable=False),
            pa.field("source_url", pa.string(), nullable=False),
            pa.field("source_row_index", pa.int64(), nullable=False),
            pa.field("source_row", pa.large_string(), nullable=False),
            pa.field("landing_key", pa.string(), nullable=False),
            pa.field("source_revision_hash", pa.string(), nullable=False),
            pa.field("first_observed_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("available_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("available_at_basis", pa.string(), nullable=False),
            pa.field("point_in_time_status", pa.string(), nullable=False),
            pa.field("usage_scope", pa.string(), nullable=False),
            pa.field("system_status", pa.string(), nullable=False),
            pa.field("reason_codes", pa.large_string(), nullable=False),
            pa.field("quarantine_issues", pa.large_string(), nullable=False),
            pa.field("source_trade_date", pa.string(), nullable=False),
            pa.field("trade_date", pa.date32(), nullable=False),
            pa.field("parse_status", pa.string(), nullable=False),
            pa.field("requested_month", pa.date32(), nullable=False),
            pa.field("response_date", pa.date32(), nullable=False),
            pa.field("open_index", pa.decimal128(18, 4), nullable=False),
            pa.field("high_index", pa.decimal128(18, 4), nullable=False),
            pa.field("low_index", pa.decimal128(18, 4), nullable=False),
            pa.field("close_index", pa.decimal128(18, 4), nullable=False),
            pa.field("benchmark_semantics", pa.string(), nullable=False),
        ),
        metadata={
            b"archive.schema_version": TAIEX_OHLC_SCHEMA_VERSION.encode(),
            b"archive.source_dataset": TAIEX_MONTHLY_OHLC_DATASET.encode(),
            b"source_row.encoding": b"canonical-json-v1",
            b"reason_codes.encoding": b"canonical-json-v1",
            b"quarantine_issues.encoding": b"canonical-json-v1",
            b"available_at.semantics": b"first-project-retrieval-only",
            b"benchmark.semantics": b"price-index-not-total-return",
            b"point_in_time.status": b"UNVERIFIED",
            b"usage.scope": b"RAW_LANDING_ONLY",
            b"system.status": b"RESEARCH_ONLY",
        },
    )


def _validate_request(
    batch: NormalizedTaiexOhlcBatch,
    request: HistoricalArchiveRequest,
) -> None:
    trade_dates = [row.trade_date for row in batch.rows]
    expected_end = batch.requested_month.replace(
        day=monthrange(batch.requested_month.year, batch.requested_month.month)[1]
    )
    if (
        request.provider_code != "TWSE"
        or request.source_dataset != TAIEX_MONTHLY_OHLC_DATASET
        or request.scheduled_market != "TWSE"
        or request.asset_type != "BENCHMARK"
        or request.source_symbol != TAIEX_OHLC_SYMBOL
        or request.source_payload_sha256 != batch.source_payload_sha256
        or request.retrieved_at != batch.retrieved_at
        or request.requested_start_date != batch.requested_month
        or request.requested_end_date != expected_end
        or not all(
            request.requested_start_date <= value <= request.requested_end_date
            for value in trade_dates
        )
    ):
        raise IngestionError(
            "TAIEX_OHLC_ARCHIVE_REQUEST_MISMATCH",
            "TAIEX OHLC batch does not match its archive request",
        )


def serialize_taiex_ohlc_parquet(
    batch: NormalizedTaiexOhlcBatch,
    *,
    request: HistoricalArchiveRequest,
) -> HistoricalArchiveArtifact:
    """Create one deterministic monthly ZSTD artifact with shared metadata."""

    _validate_request(batch, request)
    pa, pq = _pyarrow_modules()
    reason_codes = canonical_json(list(batch.reason_codes), field_name="reason_codes")
    rows = [
        {
            "archive_schema_version": TAIEX_OHLC_SCHEMA_VERSION,
            "scheduled_market": request.scheduled_market,
            "scheduled_asset_type": request.asset_type,
            "requested_start_date": request.requested_start_date,
            "requested_end_date": request.requested_end_date,
            "source_code": request.provider_code,
            "source_dataset": request.source_dataset,
            "source_symbol": request.source_symbol,
            "source_version": batch.source_version,
            "source_payload_hash": request.source_payload_sha256,
            "source_url": batch.source_url,
            "source_row_index": row.source_row_index,
            "source_row": canonical_json(list(row.source_row), field_name="source_row"),
            "landing_key": row.landing_key,
            "source_revision_hash": row.source_revision_hash,
            "first_observed_at": batch.retrieved_at,
            "available_at": batch.retrieved_at,
            "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
            "point_in_time_status": batch.point_in_time_status,
            "usage_scope": batch.usage_scope,
            "system_status": batch.system_status,
            "reason_codes": reason_codes,
            "quarantine_issues": "[]",
            "source_trade_date": row.trade_date.isoformat(),
            "trade_date": row.trade_date,
            "parse_status": "PARSED",
            "requested_month": batch.requested_month,
            "response_date": batch.response_date,
            "open_index": row.open_index,
            "high_index": row.high_index,
            "low_index": row.low_index,
            "close_index": row.close_index,
            "benchmark_semantics": "PRICE_INDEX_NOT_TOTAL_RETURN",
        }
        for row in sorted(batch.rows, key=lambda value: value.source_row_index)
    ]
    schema = taiex_ohlc_schema().with_metadata(
        {
            **(taiex_ohlc_schema().metadata or {}),
            b"archive.scheduled_market": request.scheduled_market.encode(),
            b"archive.asset_type": request.asset_type.encode(),
            b"archive.source_symbol": request.source_symbol.encode(),
            b"archive.requested_start_date": request.requested_start_date.isoformat().encode(),
            b"archive.requested_end_date": request.requested_end_date.isoformat().encode(),
            b"archive.source_payload_sha256": request.source_payload_sha256.encode(),
            b"archive.retrieved_at": request.retrieved_at.isoformat().encode(),
            b"archive.requested_month": batch.requested_month.strftime(
                "%Y-%m"
            ).encode(),
            b"source.version": batch.source_version.encode(),
            b"source.url": batch.source_url.encode(),
            b"reason_codes": reason_codes.encode(),
        }
    )
    table = pa.Table.from_pylist(rows, schema=schema)
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
    return HistoricalArchiveArtifact(
        request=request,
        object_key=build_historical_object_key(request),
        payload=payload,
        content_sha256=sha256(payload).hexdigest(),
        byte_size=len(payload),
        row_count=len(rows),
        schema_version=HISTORICAL_ARCHIVE_SCHEMA_VERSIONS[TAIEX_MONTHLY_OHLC_DATASET],
        compression=HISTORICAL_ARCHIVE_COMPRESSION,
    )
