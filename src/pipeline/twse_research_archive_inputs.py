"""TWSE scope for the shared archive-to-research input verifier."""

from __future__ import annotations

from typing import final

from src.data.archive.historical_parquet_reader import HistoricalParquetReader
from src.data.providers.twse import TAIEX_MONTHLY_OHLC_DATASET

from .research_archive_inputs import (
    ResearchArchiveInputLoader,
    ResearchArchiveProfile,
    ResearchDatasetBuildError,
    VerifiedResearchArchiveInputs,
)


_TWSE_PROFILE = ResearchArchiveProfile(
    market="TWSE",
    benchmark_provider="TWSE",
    benchmark_dataset=TAIEX_MONTHLY_OHLC_DATASET,
    benchmark_symbol="TAIEX",
    benchmark_error_prefix="TAIEX_OHLC",
    calendar_policy="EXTERNAL",
)

DAILY_BAR_FILTERS = dict(_TWSE_PROFILE.daily_filters)
TAIEX_OHLC_FILTERS = dict(_TWSE_PROFILE.benchmark_filters)


@final
class TwseResearchArchiveInputLoader(ResearchArchiveInputLoader):
    def __init__(self, reader: HistoricalParquetReader) -> None:
        super().__init__(reader, profile=_TWSE_PROFILE)


TwseResearchDatasetBuildError = ResearchDatasetBuildError
VerifiedTwseResearchArchiveInputs = VerifiedResearchArchiveInputs


__all__ = [
    "DAILY_BAR_FILTERS",
    "TAIEX_OHLC_FILTERS",
    "TwseResearchArchiveInputLoader",
    "TwseResearchDatasetBuildError",
    "VerifiedTwseResearchArchiveInputs",
]
