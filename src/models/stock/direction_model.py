"""Three-class tradability direction model using net executable returns."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module
from typing import Any, ClassVar, final

from src.labels.direction_label import (
    DirectionLabel as Direction,
    NoTradeBandConfig,
    make_direction_label,
    make_direction_labels,
    no_trade_band,
)

from ..model_contracts import validate_horizon


__all__ = [
    "Direction",
    "DirectionModel",
    "NoTradeBandConfig",
    "make_direction_label",
    "make_direction_labels",
    "no_trade_band",
]


@final
class DirectionModel:
    """Logistic baseline or LightGBM multiclass candidate.

    Returned probabilities are deliberately marked raw. A separately fitted
    probability calibrator must run before decision_policy consumes them.
    """

    output_order: ClassVar[tuple[Direction, ...]] = (
        Direction.UP,
        Direction.NEUTRAL,
        Direction.DOWN,
    )

    def __init__(
        self,
        horizon: int = 5,
        backend: str = "lightgbm",
        random_seed: int = 20260718,
        **model_params: Any,
    ) -> None:
        _ = validate_horizon(horizon)
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
                + f"missing classes: {missing}"
            )
        try:
            if self.backend == "logistic":
                model_class = import_module("sklearn.linear_model").LogisticRegression
                parameters = {"max_iter": 1000, "random_state": self.random_seed}
            else:
                model_class = import_module("lightgbm").LGBMClassifier
                parameters = {
                    "objective": "multiclass",
                    "num_class": 3,
                    "random_state": self.random_seed,
                }
        except ModuleNotFoundError as error:
            raise RuntimeError(
                f"{self.backend} direction-model dependency is not installed"
            ) from error
        parameters.update(self.model_params)
        model = model_class(**parameters)
        model.fit(features, string_labels)
        self.model = model
        return self

    def predict_raw_proba(self, features: Any) -> list[dict[str, float]]:
        if self.model is None:
            raise RuntimeError("direction model has not been fitted")
        class_positions = {
            str(label): index for index, label in enumerate(self.model.classes_)
        }
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
