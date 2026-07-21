"""Serialize one provider supplemental dataset to deterministic ZSTD Parquet."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Any, cast

from .contracts import IngestionError
from .historical_archive_contracts import (
    HISTORICAL_ARCHIVE_COMPRESSION,
    HISTORICAL_ARCHIVE_SCHEMA_VERSIONS,
    HistoricalArchiveArtifact,
    HistoricalArchiveRequest,
)
from .historical_object_key import build_historical_object_key
from .historical_parquet_serializer import canonical_json
from .historical_supplemental_contracts import SUPPLEMENTAL_DATASETS


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


def historical_supplemental_schema(source_dataset: str) -> Any:
    if source_dataset not in SUPPLEMENTAL_DATASETS:
        raise ValueError("unsupported supplemental dataset")
    pa, _ = _pyarrow_modules()
    return pa.schema(
        (
            pa.field("archive_schema_version", pa.string(), nullable=False),
            pa.field("scheduled_market", pa.string(), nullable=False),
            pa.field("scheduled_asset_type", pa.string(), nullable=False),
            pa.field("requested_start_date", pa.date32(), nullable=False),
            pa.field("requested_end_date", pa.date32(), nullable=False),
            pa.field("landing_key", pa.string(), nullable=False),
            pa.field("source_code", pa.string(), nullable=False),
            pa.field("source_dataset", pa.string(), nullable=False),
            pa.field("source_symbol", pa.string()),
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
        ),
        metadata={
            b"archive.schema_version": HISTORICAL_ARCHIVE_SCHEMA_VERSIONS[
                source_dataset
            ].encode(),
            b"archive.source_dataset": source_dataset.encode(),
            b"source_row.encoding": b"canonical-json-v1",
            b"reason_codes.encoding": b"canonical-json-v1",
            b"quarantine_issues.encoding": b"canonical-json-v1",
            b"scheduled_market.semantics": b"request-scheduling-only",
        },
    )


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


def _archive_row(
    row: Mapping[str, object], request: HistoricalArchiveRequest
) -> dict[str, object]:
    source_code = _required_text(row, "source_code")
    source_dataset = _required_text(row, "source_dataset")
    source_payload_hash = _required_text(row, "source_payload_hash")
    if source_code != request.provider_code or source_dataset != request.source_dataset:
        raise IngestionError(
            "HISTORICAL_ARCHIVE_SOURCE_INVALID",
            "archive row does not match the supplemental request",
        )
    if source_payload_hash.lower() != request.source_payload_sha256:
        raise IngestionError(
            "HISTORICAL_ARCHIVE_PAYLOAD_HASH_MISMATCH",
            "archive row does not match the requested source payload",
        )
    source_symbol = _optional_text(row, "source_symbol")
    if source_symbol is not None and source_symbol != request.source_symbol:
        raise IngestionError(
            "HISTORICAL_ARCHIVE_SYMBOL_MISMATCH",
            "archive row contains another source symbol",
        )
    trade_date = _trade_date(row)
    if trade_date is not None and not (
        request.requested_start_date <= trade_date <= request.requested_end_date
    ):
        raise IngestionError(
            "HISTORICAL_ARCHIVE_DATE_OUTSIDE_REQUEST",
            "archive row is outside the requested date range",
        )
    reason_codes = row.get("reason_codes")
    if not isinstance(reason_codes, (list, tuple)):
        raise IngestionError(
            "HISTORICAL_ARCHIVE_ROW_INVALID",
            "historical archive row contains invalid reason_codes",
        )
    raw_reason_codes = cast(Sequence[object], reason_codes)
    if any(not isinstance(reason, str) or not reason for reason in raw_reason_codes):
        raise IngestionError(
            "HISTORICAL_ARCHIVE_ROW_INVALID",
            "historical archive row contains invalid reason_codes",
        )
    row_index = row.get("source_row_index")
    if isinstance(row_index, bool) or not isinstance(row_index, int):
        raise IngestionError(
            "HISTORICAL_ARCHIVE_ROW_INVALID",
            "historical archive row contains an invalid source_row_index",
        )
    schema_version = HISTORICAL_ARCHIVE_SCHEMA_VERSIONS[request.source_dataset]
    return {
        "archive_schema_version": schema_version,
        "scheduled_market": request.scheduled_market,
        "scheduled_asset_type": request.asset_type,
        "requested_start_date": request.requested_start_date,
        "requested_end_date": request.requested_end_date,
        "landing_key": _required_text(row, "landing_key"),
        "source_code": source_code,
        "source_dataset": source_dataset,
        "source_symbol": source_symbol,
        "source_version": _required_text(row, "source_version"),
        "source_revision_hash": _required_text(row, "source_revision_hash"),
        "source_payload_hash": source_payload_hash,
        "source_url": _required_text(row, "source_url"),
        "source_row_index": row_index,
        "source_row": canonical_json(row.get("source_row"), field_name="source_row"),
        "first_observed_at": _utc_datetime(row, "first_observed_at"),
        "available_at": _utc_datetime(row, "available_at"),
        "available_at_basis": _required_text(row, "available_at_basis"),
        "identity_resolution_status": _required_text(row, "identity_resolution_status"),
        "point_in_time_status": _required_text(row, "point_in_time_status"),
        "usage_scope": _required_text(row, "usage_scope"),
        "system_status": _required_text(row, "system_status"),
        "reason_codes": canonical_json(
            [cast(str, reason) for reason in raw_reason_codes],
            field_name="reason_codes",
        ),
        "quarantine_issues": canonical_json(
            row.get("archive_quarantine_issues", []),
            field_name="archive_quarantine_issues",
        ),
        "source_trade_date": _optional_text(row, "source_trade_date"),
        "trade_date": trade_date,
        "parse_status": _required_text(row, "parse_status"),
    }


def serialize_historical_supplemental_parquet(
    rows: Sequence[Mapping[str, object]],
    *,
    request: HistoricalArchiveRequest,
) -> HistoricalArchiveArtifact:
    if request.source_dataset not in SUPPLEMENTAL_DATASETS:
        raise ValueError("request is not a supplemental dataset")
    if not rows:
        raise IngestionError(
            "HISTORICAL_ARCHIVE_EMPTY",
            "historical archive requires at least one source row",
        )
    pa, pq = _pyarrow_modules()
    archived = [_archive_row(row, request) for row in rows]
    archived.sort(
        key=lambda row: (cast(int, row["source_row_index"]), str(row["landing_key"]))
    )
    schema = historical_supplemental_schema(request.source_dataset)
    schema = schema.with_metadata(
        {
            **(schema.metadata or {}),
            b"archive.scheduled_market": request.scheduled_market.encode(),
            b"archive.asset_type": request.asset_type.encode(),
            b"archive.source_symbol": request.source_symbol.encode(),
            b"archive.requested_start_date": request.requested_start_date.isoformat().encode(),
            b"archive.requested_end_date": request.requested_end_date.isoformat().encode(),
            b"archive.source_payload_sha256": request.source_payload_sha256.encode(),
            b"archive.retrieved_at": request.retrieved_at.isoformat().encode(),
            b"archive.provider_code": request.provider_code.encode(),
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
    schema_version = HISTORICAL_ARCHIVE_SCHEMA_VERSIONS[request.source_dataset]
    return HistoricalArchiveArtifact(
        request=request,
        object_key=build_historical_object_key(request),
        payload=payload,
        content_sha256=sha256(payload).hexdigest(),
        byte_size=len(payload),
        row_count=len(archived),
        schema_version=schema_version,
        compression=HISTORICAL_ARCHIVE_COMPRESSION,
    )
