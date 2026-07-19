"""Incremental ZSTD Parquet output for TWSE research-only feature rows."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, final

from src.features.twse_price_volume_schema import (
    TWSE_PRICE_VOLUME_FEATURE_NAMES,
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
)

from .twse_archive_feature_contracts import (
    TWSE_ARCHIVE_FEATURE_DATASET_VERSION,
    TWSE_DECISION_TIME_POLICY_VERSION,
)


def _pyarrow_modules() -> tuple[Any, Any]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    return pa, pq


def twse_archive_feature_schema(
    *,
    dataset_snapshot_sha256: str,
    source_archive_snapshot_sha256: str,
    current_identity_snapshot_sha256: str,
) -> Any:
    pa, _ = _pyarrow_modules()
    fields = [
        pa.field("dataset_snapshot_sha256", pa.string(), nullable=False),
        pa.field("source_archive_snapshot_sha256", pa.string(), nullable=False),
        pa.field("current_identity_snapshot_sha256", pa.string(), nullable=False),
        pa.field("archive_id", pa.int64(), nullable=False),
        pa.field("source_object_key", pa.string(), nullable=False),
        pa.field("source_payload_sha256", pa.string(), nullable=False),
        pa.field("source_parquet_sha256", pa.string(), nullable=False),
        pa.field("security_id", pa.int64(), nullable=False),
        pa.field("listing_period_id", pa.string(), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("market", pa.string(), nullable=False),
        pa.field("asset_type", pa.string(), nullable=False),
        pa.field("listing_date", pa.date32(), nullable=False),
        pa.field("decision_date", pa.date32(), nullable=False),
        pa.field("decision_at", pa.timestamp("us", tz="Asia/Taipei"), nullable=False),
        pa.field("horizon", pa.int16(), nullable=False),
        pa.field("decision_time_policy_version", pa.string(), nullable=False),
        pa.field("feature_schema_version", pa.string(), nullable=False),
        pa.field("feature_schema_hash", pa.string(), nullable=False),
        pa.field("price_basis", pa.string(), nullable=False),
        pa.field("availability_mode", pa.string(), nullable=False),
        pa.field("latest_available_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field(
            "latest_observed_available_at",
            pa.timestamp("us", tz="UTC"),
            nullable=False,
        ),
        pa.field("point_in_time_audit_pass", pa.bool_(), nullable=False),
        pa.field("hard_fail", pa.bool_(), nullable=False),
        pa.field(
            "research_limitation_reason_codes",
            pa.list_(pa.string()),
            nullable=False,
        ),
        pa.field("hard_fail_reason_codes", pa.list_(pa.string()), nullable=False),
        pa.field("label_status", pa.string(), nullable=False),
        pa.field("usage_scope", pa.string(), nullable=False),
        pa.field("system_status", pa.string(), nullable=False),
        pa.field("reason_codes", pa.large_string(), nullable=False),
        pa.field("source_reason_codes", pa.large_string(), nullable=False),
        *(
            pa.field(feature_name, pa.float64(), nullable=False)
            for feature_name in TWSE_PRICE_VOLUME_FEATURE_NAMES
        ),
    ]
    return pa.schema(
        fields,
        metadata={
            b"dataset.version": TWSE_ARCHIVE_FEATURE_DATASET_VERSION.encode("ascii"),
            b"dataset.snapshot_sha256": dataset_snapshot_sha256.encode("ascii"),
            b"source_archive.snapshot_sha256": source_archive_snapshot_sha256.encode(
                "ascii"
            ),
            b"current_identity.snapshot_sha256": current_identity_snapshot_sha256.encode(
                "ascii"
            ),
            b"feature.schema_version": TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION.encode(
                "ascii"
            ),
            b"feature.schema_hash": TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH.encode(
                "ascii"
            ),
            b"decision_time.policy_version": TWSE_DECISION_TIME_POLICY_VERSION.encode(
                "ascii"
            ),
            b"availability.mode": b"RESEARCH_SCHEDULING_HINT",
            b"labels.status": b"LABELS_NOT_ASSEMBLED",
            b"system.status": b"RESEARCH_ONLY",
        },
    )


@final
class TwseArchiveFeatureParquetWriter:
    """Write one symbol batch at a time and atomically publish on success."""

    def __init__(
        self,
        output_path: Path,
        *,
        dataset_snapshot_sha256: str,
        source_archive_snapshot_sha256: str,
        current_identity_snapshot_sha256: str,
    ) -> None:
        _, pq = _pyarrow_modules()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path = output_path
        self.partial_path = output_path.with_name(f".{output_path.name}.partial")
        self.schema = twse_archive_feature_schema(
            dataset_snapshot_sha256=dataset_snapshot_sha256,
            source_archive_snapshot_sha256=source_archive_snapshot_sha256,
            current_identity_snapshot_sha256=current_identity_snapshot_sha256,
        )
        self._writer = pq.ParquetWriter(
            self.partial_path,
            self.schema,
            compression="zstd",
            compression_level=9,
            version="2.6",
            data_page_version="2.0",
            use_dictionary=True,
            write_statistics=True,
        )
        self.row_count = 0
        self._closed = False

    def write_rows(self, rows: Sequence[Mapping[str, object]]) -> None:
        if self._closed:
            raise RuntimeError("research Parquet writer is already closed")
        if not rows:
            return
        pa, _ = _pyarrow_modules()
        table = pa.Table.from_pylist([dict(row) for row in rows], schema=self.schema)
        self._writer.write_table(table, row_group_size=max(1, len(rows)))
        self.row_count += len(rows)

    def finish(self) -> None:
        if self._closed:
            raise RuntimeError("research Parquet writer is already closed")
        self._writer.close()
        self._closed = True
        _ = self.partial_path.replace(self.output_path)

    def abort(self) -> None:
        if not self._closed:
            self._writer.close()
            self._closed = True
        self.partial_path.unlink(missing_ok=True)


__all__ = [
    "TwseArchiveFeatureParquetWriter",
    "twse_archive_feature_schema",
]
