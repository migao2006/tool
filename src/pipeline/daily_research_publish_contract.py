"""Fail-closed cross-section requirements for automated daily research publishing."""

from __future__ import annotations

from dataclasses import dataclass


MIN_DAILY_RESEARCH_PREDICTIONS = {"TWSE": 500, "TPEX": 500}
DAILY_RESEARCH_GATES_PER_PREDICTION = 8


@dataclass(frozen=True)
class DailyResearchCoverage:
    market: str
    feature_count: int
    prediction_count: int | None = None

    def __post_init__(self) -> None:
        normalized_market = self.market.strip().upper()
        if normalized_market not in MIN_DAILY_RESEARCH_PREDICTIONS:
            raise ValueError("daily research market is unsupported")
        if self.feature_count < 0 or (
            self.prediction_count is not None and self.prediction_count < 0
        ):
            raise ValueError("daily research row counts cannot be negative")
        object.__setattr__(self, "market", normalized_market)

    def validate(self) -> None:
        minimum = MIN_DAILY_RESEARCH_PREDICTIONS[self.market]
        if self.feature_count < minimum:
            raise DailyResearchPublishContractError(
                f"{self.market}_DAILY_RESEARCH_FEATURE_COVERAGE_TOO_LOW",
                (
                    f"{self.market} daily research requires at least {minimum} "
                    "verified feature rows before inference"
                ),
            )
        if self.prediction_count is None:
            return
        if self.prediction_count < minimum:
            raise DailyResearchPublishContractError(
                f"{self.market}_DAILY_RESEARCH_PREDICTION_COVERAGE_TOO_LOW",
                (
                    f"{self.market} daily research requires at least {minimum} "
                    "predictions before publication"
                ),
            )
        if self.prediction_count != self.feature_count:
            raise DailyResearchPublishContractError(
                f"{self.market}_DAILY_RESEARCH_CROSS_SECTION_COUNT_MISMATCH",
                (
                    f"{self.market} prediction count does not match the verified "
                    "feature cross-section"
                ),
            )


class DailyResearchPublishContractError(RuntimeError):
    """Stable publication reason that can be emitted by CLI reports."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def require_daily_research_coverage(
    market: str,
    *,
    feature_count: int,
    prediction_count: int | None = None,
) -> None:
    DailyResearchCoverage(
        market=market,
        feature_count=feature_count,
        prediction_count=prediction_count,
    ).validate()


__all__ = [
    "DAILY_RESEARCH_GATES_PER_PREDICTION",
    "DailyResearchCoverage",
    "DailyResearchPublishContractError",
    "MIN_DAILY_RESEARCH_PREDICTIONS",
    "require_daily_research_coverage",
]
