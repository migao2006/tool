from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from math import isclose
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
        probabilities = (self.p_up, self.p_neutral, self.p_down)
        if any(value < 0 or value > 1 for value in probabilities):
            raise ValueError("market probabilities must be within [0, 1]")
        if not isclose(sum(probabilities), 1.0, abs_tol=1e-6):
            raise ValueError("market probabilities must sum to 1")
        if not 0 <= self.market_exposure_cap <= 1:
            raise ValueError("market_exposure_cap must be within [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("as_of_date", "decision_at", "training_end_date"):
            payload[key] = payload[key].isoformat()
        return payload

