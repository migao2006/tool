from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from math import isclose, isfinite
from typing import Any

from src.core.horizon import require_supported_horizon


@dataclass(frozen=True)
class MarketOutput:
    as_of_date: date
    decision_at: datetime
    horizon: int
    p_up: float
    p_neutral: float
    p_down: float
    market_regime: str
    forecast_market_volatility: float
    market_exposure_cap: float
    model_version: str
    training_end_date: date

    def __post_init__(self) -> None:
        require_supported_horizon(self.horizon)
        if self.decision_at.tzinfo is None or self.decision_at.utcoffset() is None:
            raise ValueError("decision_at must be timezone-aware")
        if not self.market_regime.strip() or not self.model_version.strip():
            raise ValueError("market_regime and model_version are required")
        probabilities = (self.p_up, self.p_neutral, self.p_down)
        if any(not isfinite(value) or value < 0 or value > 1 for value in probabilities):
            raise ValueError("market probabilities must be within [0, 1]")
        if not isclose(sum(probabilities), 1.0, abs_tol=1e-6):
            raise ValueError("market probabilities must sum to 1")
        if not isfinite(self.forecast_market_volatility) or self.forecast_market_volatility < 0:
            raise ValueError("forecast_market_volatility must be finite and non-negative")
        if not isfinite(self.market_exposure_cap) or not 0 <= self.market_exposure_cap <= 1:
            raise ValueError("market_exposure_cap must be within [0, 1]")
        if self.training_end_date >= self.as_of_date:
            raise ValueError("training_end_date must be earlier than as_of_date")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("as_of_date", "decision_at", "training_end_date"):
            payload[key] = payload[key].isoformat()
        return payload
