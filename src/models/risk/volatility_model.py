"""Realized/downside volatility candidates and baseline fallback policy."""

from __future__ import annotations

from importlib import import_module
from math import exp, log
from statistics import fmean
from typing import Any, Iterable, Sequence

from ..model_contracts import validate_horizon


_EPSILON = 1e-12


def realized_variance(future_log_returns: Iterable[float]) -> float:
    return sum(float(value) ** 2 for value in future_log_returns)


def downside_semivariance(future_log_returns: Iterable[float]) -> float:
    return sum(min(0.0, float(value)) ** 2 for value in future_log_returns)


def ewma_variance(log_returns: Sequence[float], decay: float = 0.94) -> float:
    if not log_returns or not 0 < decay < 1:
        raise ValueError("EWMA needs returns and a decay strictly between zero and one")
    weight = 1.0
    weighted_sum = 0.0
    total_weight = 0.0
    for value in reversed(log_returns):
        weighted_sum += weight * float(value) ** 2
        total_weight += weight
        weight *= decay
    return weighted_sum / total_weight


def har_features(realized_variances: Sequence[float]) -> tuple[float, float, float]:
    if len(realized_variances) < 22:
        raise ValueError("HAR(1/5/22) requires at least 22 trailing observations")
    return (
        float(realized_variances[-1]),
        fmean(realized_variances[-5:]),
        fmean(realized_variances[-22:]),
    )


def qlike(actual_variance: float, forecast_variance: float) -> float:
    actual = max(_EPSILON, float(actual_variance))
    forecast = max(_EPSILON, float(forecast_variance))
    ratio = actual / forecast
    return ratio - log(ratio) - 1.0


def select_production_model(fold_qlike: dict[str, Sequence[float]], candidate: str = "lightgbm") -> str:
    """Use LightGBM only when it beats EWMA and HAR in most shared folds."""

    required = {candidate, "ewma", "har"}
    if not required.issubset(fold_qlike):
        raise ValueError(f"fold results must contain {sorted(required)}")
    lengths = {len(fold_qlike[name]) for name in required}
    if len(lengths) != 1 or not next(iter(lengths)):
        raise ValueError("all model fold result arrays must have equal non-zero length")
    wins = sum(
        candidate_value < ewma_value and candidate_value < har_value
        for candidate_value, ewma_value, har_value in zip(
            fold_qlike[candidate], fold_qlike["ewma"], fold_qlike["har"]
        )
    )
    if wins > len(fold_qlike[candidate]) / 2:
        return candidate
    return min(("ewma", "har"), key=lambda name: fmean(fold_qlike[name]))


class VolatilityModel:
    """Fit log(RV + epsilon) with HAR or LightGBM."""

    def __init__(self, horizon: int = 5, backend: str = "lightgbm", random_seed: int = 20260718, **params: Any) -> None:
        validate_horizon(horizon)
        if backend not in {"har", "lightgbm"}:
            raise ValueError("trainable backend must be 'har' or 'lightgbm'")
        self.horizon = horizon
        self.backend = backend
        self.random_seed = random_seed
        self.params = params
        self.model: Any | None = None

    def fit(self, features: Any, realized_variances: Sequence[float]) -> "VolatilityModel":
        targets = [log(max(0.0, float(value)) + _EPSILON) for value in realized_variances]
        try:
            if self.backend == "har":
                model_class = import_module("sklearn.linear_model").LinearRegression
                parameters: dict[str, Any] = {}
            else:
                model_class = import_module("lightgbm").LGBMRegressor
                parameters = {"random_state": self.random_seed}
        except ModuleNotFoundError as error:
            raise RuntimeError(f"{self.backend} volatility-model dependency is not installed") from error
        parameters.update(self.params)
        self.model = model_class(**parameters)
        self.model.fit(features, targets)
        return self

    def predict_variance(self, features: Any) -> list[float]:
        if self.model is None:
            raise RuntimeError("volatility model has not been fitted")
        return [max(0.0, exp(float(value)) - _EPSILON) for value in self.model.predict(features)]
