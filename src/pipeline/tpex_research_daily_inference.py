"""TPEX-bound bundle inference entry point."""

from __future__ import annotations

from .twse_research_daily_inference import TwseDailyResearchInference


class TpexDailyResearchInference(TwseDailyResearchInference):
    def __init__(self) -> None:
        super().__init__(
            market="TPEX",
            primary_reason_code="TPEX_PRICE_ONLY_RESEARCH",
        )


__all__ = ["TpexDailyResearchInference"]
