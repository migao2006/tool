"""Market-level models that never alter individual stock ordering."""

from __future__ import annotations

from importlib import import_module
from typing import Any, Mapping, Sequence

from ..model_contracts import validate_horizon


MARKET_CLASSES = ("UP", "NEUTRAL", "DOWN")


class MarketDirectionModel:
    def __init__(
        self, horizon: int = 5, backend: str = "logistic", random_seed: int = 20260718, **model_params: Any
    ) -> None:
        validate_horizon(horizon)
        if backend not in {"logistic", "lightgbm"}:
            raise ValueError("backend must be 'logistic' or 'lightgbm'")
        self.horizon = horizon
        self.backend = backend
        self.random_seed = random_seed
        self.model_params = model_params
        self.model: Any | None = None

    def fit(self, features: Any, labels: Sequence[str]) -> "MarketDirectionModel":
        if any(label not in MARKET_CLASSES for label in labels):
            raise ValueError(f"market labels must be one of {MARKET_CLASSES}")
        try:
            if self.backend == "logistic":
                model_class = import_module("sklearn.linear_model").LogisticRegression
                parameters = {"max_iter": 1000, "random_state": self.random_seed}
            else:
                model_class = import_module("lightgbm").LGBMClassifier
                parameters = {"objective": "multiclass", "num_class": 3, "random_state": self.random_seed}
        except ModuleNotFoundError as error:
            raise RuntimeError(f"{self.backend} market-model dependency is not installed") from error
        parameters.update(self.model_params)
        self.model = model_class(**parameters)
        self.model.fit(features, labels)
        return self

    def predict_raw_proba(self, features: Any) -> list[dict[str, float]]:
        if self.model is None:
            raise RuntimeError("market model has not been fitted")
        positions = {str(label): index for index, label in enumerate(self.model.classes_)}
        return [
            {label: float(row[positions[label]]) if label in positions else 0.0 for label in MARKET_CLASSES}
            for row in self.model.predict_proba(features)
        ]


def classify_market_regime(
    trailing_trend: float,
    trailing_volatility: float,
    market_breadth: float,
    trend_threshold: float = 0.0,
    high_volatility_threshold: float = 0.02,
    broad_threshold: float = 0.5,
) -> str:
    """Describe only decision-time-observable trend × vol × breadth."""

    trend = "UPTREND" if trailing_trend > trend_threshold else "DOWNTREND" if trailing_trend < -trend_threshold else "FLAT"
    volatility = "HIGH_VOL" if trailing_volatility >= high_volatility_threshold else "LOW_VOL"
    breadth = "BROAD" if market_breadth >= broad_threshold else "NARROW"
    return f"{trend}_{volatility}_{breadth}"


def market_exposure_cap(
    direction_probabilities: Mapping[str, float],
    forecast_market_volatility: float,
    target_volatility: float,
    maximum_exposure: float,
) -> float:
    if forecast_market_volatility <= 0 or target_volatility < 0 or maximum_exposure < 0:
        raise ValueError("volatility and maximum exposure inputs must be valid")
    directional_scale = min(
        1.0,
        max(0.0, 0.5 + 0.5 * (float(direction_probabilities["UP"]) - float(direction_probabilities["DOWN"]))),
    )
    volatility_scale = min(1.0, target_volatility / forecast_market_volatility)
    return min(maximum_exposure, max(0.0, maximum_exposure * directional_scale * volatility_scale))
