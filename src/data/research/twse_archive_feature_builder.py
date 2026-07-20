"""Backward-compatible TWSE builder for the shared archive feature pipeline."""

from collections.abc import Callable
from datetime import datetime, timezone

from src.data.archive.historical_parquet_reader import HistoricalParquetReader

from .archive_feature_builder import ArchiveFeatureDatasetBuilder
from .archive_feature_contracts import ArchiveFeatureBuildError


class TwseArchiveFeatureDatasetBuilder(ArchiveFeatureDatasetBuilder):
    def __init__(
        self,
        reader: HistoricalParquetReader,
        *,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        super().__init__(reader, market="TWSE", now_fn=now_fn)


TwseArchiveFeatureBuildError = ArchiveFeatureBuildError

__all__ = ["TwseArchiveFeatureBuildError", "TwseArchiveFeatureDatasetBuilder"]
