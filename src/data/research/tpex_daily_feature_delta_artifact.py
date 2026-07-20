"""ZSTD Parquet I/O and read-back verification for TPEX feature deltas."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from src.features.tpex_price_volume_schema import (
    TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
    TPEX_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
)

from .archive_feature_market import archive_feature_market_profile
from .archive_feature_parquet import archive_feature_schema
from .tpex_daily_feature_delta_contracts import (
    TPEX_DAILY_FEATURE_DELTA_VERSION,
    TpexDailyFeatureDeltaError,
)


def _modules() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ModuleNotFoundError as error:
        raise TpexDailyFeatureDeltaError(
            "PARQUET_DEPENDENCY_MISSING",
            "pyarrow is required for TPEX feature deltas",
        ) from error
    return pa, pq


def tpex_daily_feature_delta_schema(
    *,
    dataset_snapshot_sha256: str,
    source_archive_snapshot_sha256: str,
    current_identity_snapshot_sha256: str,
    daily_bar_snapshot_sha256: str,
    as_of_date: date,
) -> Any:
    pa, _ = _modules()
    base = archive_feature_schema(
        dataset_snapshot_sha256=dataset_snapshot_sha256,
        source_archive_snapshot_sha256=source_archive_snapshot_sha256,
        current_identity_snapshot_sha256=current_identity_snapshot_sha256,
        market="TPEX",
    )
    fields = [
        *base,
        pa.field("daily_bar_snapshot_sha256", pa.string(), nullable=False),
        pa.field("source_daily_bar_id", pa.int64(), nullable=False),
        pa.field("source_daily_source_id", pa.int64(), nullable=False),
        pa.field("source_daily_version", pa.string(), nullable=False),
        pa.field(
            "source_daily_available_at",
            pa.timestamp("us", tz="UTC"),
            nullable=False,
        ),
    ]
    profile = archive_feature_market_profile("TPEX")
    return pa.schema(
        fields,
        metadata={
            b"artifact.kind": b"DAILY_FEATURE_DELTA",
            b"dataset.version": TPEX_DAILY_FEATURE_DELTA_VERSION.encode("ascii"),
            b"dataset.snapshot_sha256": dataset_snapshot_sha256.encode("ascii"),
            b"source_archive.snapshot_sha256": source_archive_snapshot_sha256.encode(
                "ascii"
            ),
            b"current_identity.snapshot_sha256": current_identity_snapshot_sha256.encode(
                "ascii"
            ),
            b"daily_bar.snapshot_sha256": daily_bar_snapshot_sha256.encode("ascii"),
            b"delta.as_of_date": as_of_date.isoformat().encode("ascii"),
            b"feature.schema_version": TPEX_PRICE_VOLUME_FEATURE_SCHEMA_VERSION.encode(
                "ascii"
            ),
            b"feature.schema_hash": TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH.encode(
                "ascii"
            ),
            b"decision_time.policy_version": profile.decision_time_policy_version.encode(
                "ascii"
            ),
            b"availability.mode": b"RESEARCH_SCHEDULING_HINT",
            b"labels.status": b"LABELS_NOT_ASSEMBLED",
            b"usage.scope": b"FEATURE_RESEARCH_ONLY",
            b"system.status": b"RESEARCH_ONLY",
            b"point_in_time.status": b"UNVERIFIED",
            b"horizon": b"5",
        },
    )


class TpexDailyFeatureDeltaWriter:
    def __init__(
        self,
        output_path: Path,
        *,
        dataset_snapshot_sha256: str,
        source_archive_snapshot_sha256: str,
        current_identity_snapshot_sha256: str,
        daily_bar_snapshot_sha256: str,
        as_of_date: date,
    ) -> None:
        _, pq = _modules()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path = output_path
        self.partial_path = output_path.with_name(f".{output_path.name}.partial")
        self.schema = tpex_daily_feature_delta_schema(
            dataset_snapshot_sha256=dataset_snapshot_sha256,
            source_archive_snapshot_sha256=source_archive_snapshot_sha256,
            current_identity_snapshot_sha256=current_identity_snapshot_sha256,
            daily_bar_snapshot_sha256=daily_bar_snapshot_sha256,
            as_of_date=as_of_date,
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
        self._closed = False

    def write_rows(self, rows: Sequence[Mapping[str, object]]) -> None:
        if self._closed:
            raise RuntimeError("TPEX feature delta writer is closed")
        if not rows:
            return
        pa, _ = _modules()
        table = pa.Table.from_pylist([dict(row) for row in rows], schema=self.schema)
        self._writer.write_table(table, row_group_size=max(1, len(rows)))

    def finish(self) -> None:
        if self._closed:
            raise RuntimeError("TPEX feature delta writer is closed")
        self._writer.close()
        self._closed = True
        _ = self.partial_path.replace(self.output_path)

    def abort(self) -> None:
        if not self._closed:
            self._writer.close()
            self._closed = True
        self.partial_path.unlink(missing_ok=True)


__all__ = [
    "TpexDailyFeatureDeltaWriter",
    "tpex_daily_feature_delta_schema",
]
