"""Serialize normalized historical daily bars to fixed-schema Parquet."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false
# PyArrow does not publish a complete typed surface. Keep that untyped boundary
# isolated in this serialization adapter instead of weakening project-wide checks.

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from typing import Any, cast

from .contracts import IngestionError
from .historical_archive_contracts import (
    HISTORICAL_ARCHIVE_COMPRESSION,
    HISTORICAL_ARCHIVE_SCHEMA_VERSION,
    HistoricalArchiveArtifact,
    HistoricalArchiveRequest,
)
from .historical_object_key import build_historical_object_key


_REQUIRED_TEXT_FIELDS = (
    "landing_key",
    "source_code",
    "source_dataset",
    "source_market_basis",
    "source_version",
    "source_revision_hash",
    "source_payload_hash",
    "source_url",
    "available_at_basis",
    "identity_resolution_status",
    "point_in_time_status",
    "usage_scope",
    "system_status",
    "parse_status",
)


def _pyarrow_modules() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ModuleNotFoundError as error:
        raise IngestionError(
            "PARQUET_DEPENDENCY_MISSING",
            "pyarrow is required to serialize historical archives",
        ) from error
    return pa, pq


def historical_parquet_schema() -> Any:
    """Return the versioned, fixed Arrow schema for one archive object."""

    pa, _ = _pyarrow_modules()
    fields = (
        pa.field("archive_schema_version", pa.string(), nullable=False),
        pa.field("scheduled_market", pa.string(), nullable=False),
        pa.field("scheduled_asset_type", pa.string(), nullable=False),
        pa.field("requested_start_date", pa.date32(), nullable=False),
        pa.field("requested_end_date", pa.date32(), nullable=False),
        pa.field("landing_key", pa.string(), nullable=False),
        pa.field("source_code", pa.string(), nullable=False),
        pa.field("source_dataset", pa.string(), nullable=False),
        pa.field("source_symbol", pa.string()),
        pa.field("source_market_claim", pa.string()),
        pa.field("source_market_basis", pa.string(), nullable=False),
        pa.field("source_version", pa.string(), nullable=False),
        pa.field("source_revision_hash", pa.string(), nullable=False),
        pa.field("source_payload_hash", pa.string(), nullable=False),
        pa.field("source_url", pa.string(), nullable=False),
        pa.field("source_row_index", pa.int64(), nullable=False),
        pa.field("source_row", pa.large_string(), nullable=False),
        pa.field("first_observed_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("available_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("available_at_basis", pa.string(), nullable=False),
        pa.field("identity_resolution_status", pa.string(), nullable=False),
        pa.field("point_in_time_status", pa.string(), nullable=False),
        pa.field("usage_scope", pa.string(), nullable=False),
        pa.field("system_status", pa.string(), nullable=False),
        pa.field("reason_codes", pa.large_string(), nullable=False),
        pa.field("quarantine_issues", pa.large_string(), nullable=False),
        pa.field("source_trade_date", pa.string()),
        pa.field("trade_date", pa.date32()),
        pa.field("parse_status", pa.string(), nullable=False),
        pa.field("open_price", pa.string()),
        pa.field("high_price", pa.string()),
        pa.field("low_price", pa.string()),
        pa.field("close_price", pa.string()),
        pa.field("trading_volume", pa.string()),
        pa.field("trading_value", pa.string()),
        pa.field("trade_count", pa.int64()),
    )
    return pa.schema(
        fields,
        metadata={
            b"archive.schema_version": HISTORICAL_ARCHIVE_SCHEMA_VERSION.encode(),
            b"source_row.encoding": b"canonical-json-v1",
            b"reason_codes.encoding": b"canonical-json-v1",
            b"quarantine_issues.encoding": b"canonical-json-v1",
            b"scheduled_market.semantics": b"request-scheduling-only",
        },
    )


def canonical_json(value: object, *, field_name: str) -> str:
    """Encode JSON without platform-dependent whitespace or key ordering."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise IngestionError(
            "HISTORICAL_ARCHIVE_JSON_INVALID",
            f"{field_name} cannot be represented as canonical JSON",
        ) from error


def _required_text(row: Mapping[str, object], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        raise IngestionError(
            "HISTORICAL_ARCHIVE_ROW_INVALID",
            f"historical archive row is missing {name}",
        )
    return value.strip()


def _optional_text(row: Mapping[str, object], name: str) -> str | None:
    value = row.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise IngestionError(
            "HISTORICAL_ARCHIVE_ROW_INVALID",
            f"historical archive row contains an invalid {name}",
        )
    return value


def _integer(row: Mapping[str, object], name: str, *, nullable: bool) -> int | None:
    value = row.get(name)
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise IngestionError(
            "HISTORICAL_ARCHIVE_ROW_INVALID",
            f"historical archive row contains an invalid {name}",
        )
    return value


def _utc_datetime(row: Mapping[str, object], name: str) -> datetime:
    value = row.get(name)
    try:
        parsed = (
            value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        )
    except ValueError as error:
        raise IngestionError(
            "HISTORICAL_ARCHIVE_ROW_INVALID",
            f"historical archive row contains an invalid {name}",
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise IngestionError(
            "HISTORICAL_ARCHIVE_ROW_INVALID",
            f"historical archive row contains a timezone-naive {name}",
        )
    return parsed.astimezone(timezone.utc)


def _trade_date(row: Mapping[str, object]) -> date | None:
    value = row.get("trade_date")
    if value is None:
        return None
    try:
        return value if type(value) is date else date.fromisoformat(str(value))
    except ValueError as error:
        raise IngestionError(
            "HISTORICAL_ARCHIVE_ROW_INVALID",
            "historical archive row contains an invalid trade_date",
        ) from error


def _reason_codes(row: Mapping[str, object]) -> str:
    value = row.get("reason_codes")
    if not isinstance(value, (list, tuple)):
        raise IngestionError(
            "HISTORICAL_ARCHIVE_ROW_INVALID",
            "historical archive row contains invalid reason_codes",
        )
    raw_codes = cast(Sequence[object], value)
    if any(not isinstance(reason, str) or not reason for reason in raw_codes):
        raise IngestionError(
            "HISTORICAL_ARCHIVE_ROW_INVALID",
            "historical archive row contains invalid reason_codes",
        )
    reason_codes = [cast(str, reason) for reason in raw_codes]
    return canonical_json(reason_codes, field_name="reason_codes")


def _archive_row(
    row: Mapping[str, object], request: HistoricalArchiveRequest
) -> dict[str, object]:
    required = {name: _required_text(row, name) for name in _REQUIRED_TEXT_FIELDS}
    if (
        required["source_code"] != "FINMIND"
        or required["source_dataset"] != "daily_bars"
    ):
        raise IngestionError(
            "HISTORICAL_ARCHIVE_SOURCE_INVALID",
            "historical archive rows must be normalized FinMind daily bars",
        )
    if required["source_payload_hash"].lower() != request.source_payload_sha256:
        raise IngestionError(
            "HISTORICAL_ARCHIVE_PAYLOAD_HASH_MISMATCH",
            "historical archive row does not match the requested source payload",
        )
    source_symbol = _optional_text(row, "source_symbol")
    if source_symbol is not None and source_symbol != request.source_symbol:
        raise IngestionError(
            "HISTORICAL_ARCHIVE_SYMBOL_MISMATCH",
            "historical archive row contains another source symbol",
        )
    parsed_trade_date = _trade_date(row)
    if parsed_trade_date is not None and not (
        request.requested_start_date <= parsed_trade_date <= request.requested_end_date
    ):
        raise IngestionError(
            "HISTORICAL_ARCHIVE_DATE_OUTSIDE_REQUEST",
            "historical archive row is outside the requested date range",
        )

    return {
        "archive_schema_version": HISTORICAL_ARCHIVE_SCHEMA_VERSION,
        "scheduled_market": request.scheduled_market,
        "scheduled_asset_type": request.asset_type,
        "requested_start_date": request.requested_start_date,
        "requested_end_date": request.requested_end_date,
        **required,
        "source_symbol": source_symbol,
        # Preserve provider provenance. scheduled_market is deliberately separate.
        "source_market_claim": _optional_text(row, "source_market_claim"),
        "source_row_index": _integer(row, "source_row_index", nullable=False),
        "source_row": canonical_json(row.get("source_row"), field_name="source_row"),
        "first_observed_at": _utc_datetime(row, "first_observed_at"),
        "available_at": _utc_datetime(row, "available_at"),
        "reason_codes": _reason_codes(row),
        "quarantine_issues": canonical_json(
            row.get("archive_quarantine_issues", []),
            field_name="archive_quarantine_issues",
        ),
        "source_trade_date": _optional_text(row, "source_trade_date"),
        "trade_date": parsed_trade_date,
        "open_price": _optional_text(row, "open_price"),
        "high_price": _optional_text(row, "high_price"),
        "low_price": _optional_text(row, "low_price"),
        "close_price": _optional_text(row, "close_price"),
        "trading_volume": _optional_text(row, "trading_volume"),
        "trading_value": _optional_text(row, "trading_value"),
        "trade_count": _integer(row, "trade_count", nullable=True),
    }


def serialize_historical_parquet(
    rows: Sequence[Mapping[str, object]],
    *,
    request: HistoricalArchiveRequest,
) -> HistoricalArchiveArtifact:
    """Create a deterministic ZSTD Parquet artifact from normalized rows."""

    if not rows:
        raise IngestionError(
            "HISTORICAL_ARCHIVE_EMPTY",
            "historical archive requires at least one source row",
        )
    pa, pq = _pyarrow_modules()
    archived_rows = [_archive_row(row, request) for row in rows]
    archived_rows.sort(
        key=lambda row: (
            cast(int, row["source_row_index"]),
            str(row["landing_key"]),
            str(row["source_revision_hash"]),
            str(row["source_row"]),
        )
    )
    schema = historical_parquet_schema()
    request_metadata = {
        b"archive.scheduled_market": request.scheduled_market.encode("ascii"),
        b"archive.asset_type": request.asset_type.encode("ascii"),
        b"archive.source_symbol": request.source_symbol.encode("ascii"),
        b"archive.requested_start_date": request.requested_start_date.isoformat().encode(),
        b"archive.requested_end_date": request.requested_end_date.isoformat().encode(),
        b"archive.source_payload_sha256": request.source_payload_sha256.encode("ascii"),
        b"archive.retrieved_at": request.retrieved_at.isoformat().encode("ascii"),
    }
    schema = schema.with_metadata({**(schema.metadata or {}), **request_metadata})
    table = pa.Table.from_pylist(archived_rows, schema=schema)
    output = pa.BufferOutputStream()
    pq.write_table(
        table,
        output,
        compression=HISTORICAL_ARCHIVE_COMPRESSION.lower(),
        compression_level=9,
        version="2.6",
        data_page_version="2.0",
        use_dictionary=(
            "scheduled_market",
            "scheduled_asset_type",
            "source_code",
            "source_dataset",
            "source_market_basis",
            "available_at_basis",
            "identity_resolution_status",
            "point_in_time_status",
            "usage_scope",
            "system_status",
            "parse_status",
        ),
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
        row_count=len(archived_rows),
    )
