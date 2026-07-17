from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from math import isclose
from typing import Any

from src.core.horizon import require_supported_horizon


DECISIONS = {"CANDIDATE", "WATCH", "NO_TRADE"}
MARKETS = {"LISTED", "OTC"}


@dataclass(frozen=True)
class StockPredictionOutput:
    as_of_date: date
    decision_at: datetime
    symbol: str
    market: str
    industry: str | None
    horizon: int
    rank_score: float
    global_rank: int
    global_rank_percentile: float
    industry_rank: int | None
    industry_rank_percentile: float | None
    calibrated_p_up: float
    calibrated_p_neutral: float
    calibrated_p_down: float
    calibration_version: str
    gross_q10: float
    gross_q50: float
    gross_q90: float
    net_q10: float
    net_q50: float
    net_q90: float
    interval_width: float
    calibration_status: str
    forecast_volatility: float | None
    downside_risk: float | None
    market_regime: str | None
    market_exposure_cap: float
    estimated_round_trip_cost: float
    data_quality_status: str
    decision: str
    reason_codes: tuple[str, ...]
    model_version: str
    feature_schema_hash: str
    cost_profile_version: str
    training_end_date: date
    source_dates: dict[str, date | str]
    latest_available_at: datetime

    def __post_init__(self) -> None:
        require_supported_horizon(self.horizon)
        if self.market not in MARKETS:
            raise ValueError("ordinary-stock output market must be LISTED or OTC")
        if self.decision not in DECISIONS:
            raise ValueError(f"unsupported decision: {self.decision}")
        if not 0 <= self.rank_score <= 100:
            raise ValueError("Rank Score must be a 0-100 cross-sectional percentile")
        if self.global_rank < 1:
            raise ValueError("global_rank must be positive")
        if not 0 <= self.global_rank_percentile <= 1:
            raise ValueError("global_rank_percentile must be within [0, 1]")
        if self.industry_rank_percentile is not None and not 0 <= self.industry_rank_percentile <= 1:
            raise ValueError("industry_rank_percentile must be within [0, 1]")
        probabilities = (
            self.calibrated_p_up,
            self.calibrated_p_neutral,
            self.calibrated_p_down,
        )
        if any(value < 0 or value > 1 for value in probabilities):
            raise ValueError("calibrated probabilities must be within [0, 1]")
        if not isclose(sum(probabilities), 1.0, abs_tol=1e-6):
            raise ValueError("calibrated probabilities must sum to 1")
        if not self.gross_q10 <= self.gross_q50 <= self.gross_q90:
            raise ValueError("gross quantiles must be monotonic")
        if not self.net_q10 <= self.net_q50 <= self.net_q90:
            raise ValueError("net quantiles must be monotonic")
        if self.latest_available_at > self.decision_at:
            raise ValueError("latest_available_at cannot exceed decision_at")
        if self.training_end_date > self.as_of_date:
            raise ValueError("training_end_date cannot be later than as_of_date")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rank_score"] = payload.pop("rank_score")
        for key in ("as_of_date", "decision_at", "training_end_date", "latest_available_at"):
            payload[key] = payload[key].isoformat()
        payload["reason_codes"] = list(self.reason_codes)
        payload["source_dates"] = {
            key: value.isoformat() if isinstance(value, date) else value
            for key, value in self.source_dates.items()
        }
        return payload
