"""TPEX scope for the shared archive-to-research input verifier."""

from __future__ import annotations

from typing import final

from src.data.archive.historical_parquet_reader import HistoricalParquetReader
from src.data.ingestion.tpex_ohlc_contracts import TPEX_OHLC_SYMBOL
from src.data.providers.tpex import TPEX_MONTHLY_OHLC_DATASET

from .research_archive_inputs import (
    ResearchArchiveInputLoader,
    ResearchArchiveProfile,
    ResearchDatasetBuildError,
    VerifiedResearchArchiveInputs,
)


_TPEX_PROFILE = ResearchArchiveProfile(
    market="TPEX",
    benchmark_provider="TPEX",
    benchmark_dataset=TPEX_MONTHLY_OHLC_DATASET,
    benchmark_symbol=TPEX_OHLC_SYMBOL,
    benchmark_error_prefix="TPEX_OHLC",
    calendar_policy="BENCHMARK_DERIVED",
)

TPEX_DAILY_BAR_FILTERS = dict(_TPEX_PROFILE.daily_filters)
TPEX_OHLC_FILTERS = dict(_TPEX_PROFILE.benchmark_filters)


@final
class TpexResearchArchiveInputLoader(ResearchArchiveInputLoader):
    def __init__(self, reader: HistoricalParquetReader) -> None:
        super().__init__(reader, profile=_TPEX_PROFILE)


TpexResearchDatasetBuildError = ResearchDatasetBuildError
VerifiedTpexResearchArchiveInputs = VerifiedResearchArchiveInputs


__all__ = [
    "TPEX_DAILY_BAR_FILTERS",
    "TPEX_OHLC_FILTERS",
    "TpexResearchArchiveInputLoader",
    "TpexResearchDatasetBuildError",
    "VerifiedTpexResearchArchiveInputs",
]
