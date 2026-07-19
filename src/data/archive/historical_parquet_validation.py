"""Validate fixed-schema Parquet contents after R2 byte verification."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
from types import MappingProxyType
from typing import Any, cast

from src.data.ingestion.historical_archive_contracts import (
    HISTORICAL_ARCHIVE_COMPRESSION,
)
from src.data.ingestion.historical_benchmark_contracts import BENCHMARK_DATASET
from src.data.ingestion.historical_benchmark_parquet import (
    historical_benchmark_schema,
)
from src.data.ingestion.historical_parquet_serializer import (
    historical_parquet_schema,
)
from src.data.ingestion.historical_supplemental_contracts import SUPPLEMENTAL_DATASETS
from src.data.ingestion.historical_supplemental_parquet import (
    historical_supplemental_schema,
)
from src.data.ingestion.taiex_ohlc_parquet import taiex_ohlc_schema
from src.data.providers.twse import TAIEX_MONTHLY_OHLC_DATASET

from .contracts import (
    HistoricalArchiveManifest,
    HistoricalArchiveReadError,
)
from .taiex_ohlc_validation import validate_taiex_ohlc_rows


def _fail(reason_code: str, message: str) -> HistoricalArchiveReadError:
    return HistoricalArchiveReadError(reason_code, message)


def _pyarrow_modules() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ModuleNotFoundError as error:
        raise _fail(
            "HISTORICAL_ARCHIVE_PARQUET_DEPENDENCY_MISSING",
            "pyarrow is required to read historical archives",
        ) from error
    return pa, pq


def _utc_datetime(value: object, *, field: str) -> datetime:
    try:
        parsed = (
            value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        )
    except ValueError as error:
        raise _fail(
            "HISTORICAL_ARCHIVE_PARQUET_ROW_INVALID",
            f"The historical archive contains an invalid {field}",
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _fail(
            "HISTORICAL_ARCHIVE_PARQUET_ROW_INVALID",
            f"The historical archive contains a timezone-naive {field}",
        )
    return parsed.astimezone(timezone.utc)


def _date(value: object, *, field: str) -> date:
    if type(value) is date:
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise _fail(
            "HISTORICAL_ARCHIVE_PARQUET_ROW_INVALID",
            f"The historical archive contains an invalid {field}",
        ) from error


def _read_table(payload: bytes, manifest: HistoricalArchiveManifest) -> Any:
    try:
        pa, pq = _pyarrow_modules()
        parquet_file = pq.ParquetFile(pa.BufferReader(payload))
        if parquet_file.metadata.num_rows != manifest.row_count:
            raise _fail(
                "HISTORICAL_ARCHIVE_ROW_COUNT_MISMATCH",
                "Parquet row count does not match the archive manifest",
            )
        compressions = {
            parquet_file.metadata.row_group(group).column(column).compression
            for group in range(parquet_file.metadata.num_row_groups)
            for column in range(parquet_file.metadata.num_columns)
        }
        if compressions != {HISTORICAL_ARCHIVE_COMPRESSION}:
            raise _fail(
                "HISTORICAL_ARCHIVE_COMPRESSION_MISMATCH",
                "Historical Parquet columns do not use the required compression",
            )
        table = parquet_file.read()
    except HistoricalArchiveReadError:
        raise
    except Exception as error:
        raise _fail(
            "HISTORICAL_ARCHIVE_PARQUET_INVALID",
            "Historical archive bytes are not a readable fixed-schema Parquet file",
        ) from error
    if manifest.source_dataset == "daily_bars":
        expected_schema = historical_parquet_schema()
    elif manifest.source_dataset in SUPPLEMENTAL_DATASETS:
        expected_schema = historical_supplemental_schema(manifest.source_dataset)
    elif manifest.source_dataset == BENCHMARK_DATASET:
        expected_schema = historical_benchmark_schema()
    elif manifest.source_dataset == TAIEX_MONTHLY_OHLC_DATASET:
        expected_schema = taiex_ohlc_schema()
    else:
        raise _fail(
            "HISTORICAL_ARCHIVE_SCHEMA_UNSUPPORTED",
            "Historical archive dataset is not supported",
        )
    if not table.schema.equals(expected_schema, check_metadata=False):
        raise _fail(
            "HISTORICAL_ARCHIVE_SCHEMA_MISMATCH",
            "Historical Parquet fields do not match the fixed archive schema",
        )
    metadata = cast(Mapping[bytes, bytes], table.schema.metadata or {})
    fixed_metadata = cast(Mapping[bytes, bytes], expected_schema.metadata or {})
    expected_metadata: dict[bytes, bytes] = {
        **fixed_metadata,
        b"archive.scheduled_market": manifest.scheduled_market.encode("ascii"),
        b"archive.asset_type": manifest.asset_type.encode("ascii"),
        b"archive.source_symbol": manifest.source_symbol.encode("ascii"),
        b"archive.requested_start_date": manifest.requested_start_date.isoformat().encode(),
        b"archive.requested_end_date": manifest.requested_end_date.isoformat().encode(),
        b"archive.source_payload_sha256": manifest.source_payload_hash.encode("ascii"),
        b"archive.retrieved_at": manifest.first_observed_at.isoformat().encode("ascii"),
    }
    if manifest.provider_code != "FINMIND":
        expected_metadata[b"archive.provider_code"] = manifest.provider_code.encode(
            "ascii"
        )
    if any(metadata.get(key) != value for key, value in expected_metadata.items()):
        raise _fail(
            "HISTORICAL_ARCHIVE_SCHEMA_METADATA_MISMATCH",
            "Historical Parquet schema metadata does not match the archive manifest",
        )
    return table


def _verified_rows(
    table: Any,
    manifest: HistoricalArchiveManifest,
) -> tuple[Mapping[str, object], ...]:
    raw_rows = cast(list[dict[str, object]], table.to_pylist())
    if len(raw_rows) != manifest.row_count:
        raise _fail(
            "HISTORICAL_ARCHIVE_ROW_COUNT_MISMATCH",
            "Decoded row count does not match the archive manifest",
        )

    parsed_count = 0
    quarantined_count = 0
    trade_dates: list[date] = []
    sort_keys: list[tuple[int, str, str, str]] = []
    for row in raw_rows:
        parse_status = row.get("parse_status")
        if parse_status == "PARSED":
            parsed_count += 1
        elif parse_status == "QUARANTINED":
            quarantined_count += 1
        else:
            raise _fail(
                "HISTORICAL_ARCHIVE_PARQUET_ROW_INVALID",
                "Historical archive contains an unknown parse status",
            )

        if (
            row.get("archive_schema_version") != manifest.schema_version
            or row.get("scheduled_market") != manifest.scheduled_market
            or row.get("scheduled_asset_type") != manifest.asset_type
            or row.get("requested_start_date") != manifest.requested_start_date
            or row.get("requested_end_date") != manifest.requested_end_date
            or row.get("source_code") != manifest.provider_code
            or row.get("source_dataset") != manifest.source_dataset
            or row.get("source_version") != manifest.source_version
            or row.get("source_payload_hash") != manifest.source_payload_hash
            or row.get("point_in_time_status") != manifest.point_in_time_status
            or row.get("usage_scope") != manifest.usage_scope
            or row.get("system_status") != manifest.system_status
            or _utc_datetime(row.get("first_observed_at"), field="first_observed_at")
            != manifest.first_observed_at
        ):
            raise _fail(
                "HISTORICAL_ARCHIVE_PARQUET_ROW_MISMATCH",
                "Historical archive row provenance does not match its manifest",
            )

        source_symbol = row.get("source_symbol")
        if source_symbol is not None and source_symbol != manifest.source_symbol:
            raise _fail(
                "HISTORICAL_ARCHIVE_SYMBOL_MISMATCH",
                "Historical archive contains a row for another symbol",
            )
        if parse_status == "PARSED" and source_symbol != manifest.source_symbol:
            raise _fail(
                "HISTORICAL_ARCHIVE_SYMBOL_MISMATCH",
                "A parsed historical row is missing its manifest symbol",
            )

        trade_date_value = row.get("trade_date")
        if trade_date_value is not None:
            parsed_date = _date(trade_date_value, field="trade_date")
            if not (
                manifest.requested_start_date
                <= parsed_date
                <= manifest.requested_end_date
            ):
                raise _fail(
                    "HISTORICAL_ARCHIVE_DATE_MISMATCH",
                    "Historical archive contains a date outside its request",
                )
            trade_dates.append(parsed_date)
        elif parse_status == "PARSED":
            raise _fail(
                "HISTORICAL_ARCHIVE_DATE_MISMATCH",
                "A parsed historical row is missing its trade date",
            )

        index = row.get("source_row_index")
        landing_key = row.get("landing_key")
        revision_hash = row.get("source_revision_hash")
        source_row = row.get("source_row")
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not isinstance(landing_key, str)
            or not isinstance(revision_hash, str)
            or not isinstance(source_row, str)
        ):
            raise _fail(
                "HISTORICAL_ARCHIVE_PARQUET_ROW_INVALID",
                "Historical archive contains an invalid deterministic sort key",
            )
        sort_keys.append((index, landing_key, revision_hash, source_row))

    if (
        parsed_count != manifest.parsed_row_count
        or quarantined_count != manifest.quarantined_row_count
    ):
        raise _fail(
            "HISTORICAL_ARCHIVE_PARSE_COUNT_MISMATCH",
            "Historical archive parse counts do not match its manifest",
        )
    if not trade_dates or (
        min(trade_dates) != manifest.min_trade_date
        or max(trade_dates) != manifest.max_trade_date
    ):
        raise _fail(
            "HISTORICAL_ARCHIVE_DATE_MISMATCH",
            "Historical archive date bounds do not match its manifest",
        )
    if sort_keys != sorted(sort_keys):
        raise _fail(
            "HISTORICAL_ARCHIVE_SORT_ORDER_INVALID",
            "Historical archive rows are not in deterministic source order",
        )
    return tuple(MappingProxyType(row) for row in raw_rows)


def validate_historical_parquet(
    payload: bytes,
    manifest: HistoricalArchiveManifest,
) -> tuple[Mapping[str, object], ...]:
    """Return immutable decoded rows only after all Parquet checks pass."""

    rows = _verified_rows(_read_table(payload, manifest), manifest)
    if manifest.source_dataset == TAIEX_MONTHLY_OHLC_DATASET:
        validate_taiex_ohlc_rows(rows, manifest)
    return rows
