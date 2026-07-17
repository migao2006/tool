"""Three-class tradability direction model using net executable returns."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from importlib import import_module
from math import sqrt
from typing import Any, Iterable, Sequence

from ..model_contracts import validate_horizon


class Direction(str, Enum):
    UP = "UP"
    NEUTRAL = "NEUTRAL"
    DOWN = "DOWN"


@dataclass(frozen=True)
class NoTradeBandConfig:
    horizon: int = 5
    min_edge_h: float = 0.005
    k_h: float = 0.35

    def __post_init__(self) -> None:
        validate_horizon(self.horizon)
        if self.min_edge_h < 0 or self.k_h < 0:
            raise ValueError("no-trade band parameters must be non-negative")


def no_trade_band(trailing_volatility: float, config: NoTradeBandConfig) -> float:
    if trailing_volatility < 0:
        raise ValueError("trailing_volatility must be non-negative")
    return max(config.min_edge_h, config.k_h * trailing_volatility * sqrt(config.horizon))


def make_direction_label(net_return: float, trailing_volatility: float, config: NoTradeBandConfig) -> Direction:
    band = no_trade_band(trailing_volatility, config)
    if net_return > band:
        return Direction.UP
    if net_return < -band:
        return Direction.DOWN
    return Direction.NEUTRAL


def make_direction_labels(
    net_returns: Iterable[float], trailing_volatilities: Iterable[float], config: NoTradeBandConfig
) -> list[Direction]:
    returns = list(net_returns)
    volatilities = list(trailing_volatilities)
    if len(returns) != len(volatilities):
        raise ValueError("returns and volatilities must have equal length")
    return [make_direction_label(value, volatility, config) for value, volatility in zip(returns, volatilities)]


class DirectionModel:
    """Logistic baseline or LightGBM multiclass candidate.

    Returned probabilities are deliberately marked raw. A separately fitted
    probability calibrator must run before decision_policy consumes them.
    """

    output_order = (Direction.UP, Direction.NEUTRAL, Direction.DOWN)

    def __init__(
        self, horizon: int = 5, backend: str = "lightgbm", random_seed: int = 20260718, **model_params: Any
    ) -> None:
        validate_horizon(horizon)
        if backend not in {"logistic", "lightgbm"}:
            raise ValueError("backend must be 'logistic' or 'lightgbm'")
        self.horizon = horizon
        self.backend = backend
        self.random_seed = random_seed
        self.model_params = model_params
        self.model: Any | None = None

    def fit(self, features: Any, labels: Sequence[Direction | str]) -> "DirectionModel":
        string_labels = [Direction(label).value for label in labels]
        observed_classes = set(string_labels)
        required_classes = {direction.value for direction in self.output_order}
        if observed_classes != required_classes:
            missing = sorted(required_classes.difference(observed_classes))
            raise ValueError(
                "direction training requires UP, NEUTRAL, and DOWN in every fold; "
                f"missing classes: {missing}"
            )
        try:
            if self.backend == "logistic":
                model_class = import_module("sklearn.linear_model").LogisticRegression
                parameters = {"max_iter": 1000, "random_state": self.random_seed}
            else:
                model_class = import_module("lightgbm").LGBMClassifier
                parameters = {"objective": "multiclass", "num_class": 3, "random_state": self.random_seed}
        except ModuleNotFoundError as error:
            raise RuntimeError(f"{self.backend} direction-model dependency is not installed") from error
        parameters.update(self.model_params)
        self.model = model_class(**parameters)
        self.model.fit(features, string_labels)
        return self

    def predict_raw_proba(self, features: Any) -> list[dict[str, float]]:
        if self.model is None:
            raise RuntimeError("direction model has not been fitted")
        class_positions = {str(label): index for index, label in enumerate(self.model.classes_)}
        rows: list[dict[str, float]] = []
        for probabilities in self.model.predict_proba(features):
            row = {
                direction.value: float(probabilities[class_positions[direction.value]])
                if direction.value in class_positions
                else 0.0
                for direction in self.output_order
            }
            rows.append(row)
        return rows
