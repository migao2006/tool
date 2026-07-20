"""TPEX common-stock archive-to-feature research builder."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from src.data.archive.historical_parquet_reader import HistoricalParquetReader

from .archive_feature_builder import ArchiveFeatureDatasetBuilder


class TpexArchiveFeatureDatasetBuilder(ArchiveFeatureDatasetBuilder):
    def __init__(
        self,
        reader: HistoricalParquetReader,
        *,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        super().__init__(reader, market="TPEX", now_fn=now_fn)


__all__ = ["TpexArchiveFeatureDatasetBuilder"]
