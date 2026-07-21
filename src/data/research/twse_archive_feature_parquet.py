"""Backward-compatible TWSE Parquet entry point for archive features."""

# pyright: reportAny=false, reportExplicitAny=false

from pathlib import Path
from typing import Any

from .archive_feature_parquet import (
    ArchiveFeatureParquetWriter,
    archive_feature_schema,
)


def twse_archive_feature_schema(
    *,
    dataset_snapshot_sha256: str,
    source_archive_snapshot_sha256: str,
    current_identity_snapshot_sha256: str,
) -> Any:
    return archive_feature_schema(
        dataset_snapshot_sha256=dataset_snapshot_sha256,
        source_archive_snapshot_sha256=source_archive_snapshot_sha256,
        current_identity_snapshot_sha256=current_identity_snapshot_sha256,
        market="TWSE",
    )


class TwseArchiveFeatureParquetWriter(ArchiveFeatureParquetWriter):
    def __init__(
        self,
        output_path: Path,
        *,
        dataset_snapshot_sha256: str,
        source_archive_snapshot_sha256: str,
        current_identity_snapshot_sha256: str,
    ) -> None:
        super().__init__(
            output_path,
            dataset_snapshot_sha256=dataset_snapshot_sha256,
            source_archive_snapshot_sha256=source_archive_snapshot_sha256,
            current_identity_snapshot_sha256=current_identity_snapshot_sha256,
            market="TWSE",
        )


__all__ = ["TwseArchiveFeatureParquetWriter", "twse_archive_feature_schema"]
