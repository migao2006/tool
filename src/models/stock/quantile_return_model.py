"""Independent gross executable-return quantile models."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Sequence

from ...calibration.interval_calibrator import IntervalCalibrator, is_crossed, reorder_quantiles
from ..model_contracts import validate_horizon


@dataclass(frozen=True)
class QuantilePrediction:
    gross_q10: float
    gross_q50: float
    gross_q90: float
    net_q10: float
    net_q50: float
    net_q90: float
    interval_width: float
    raw_crossed: bool
    calibration_status: str


class QuantileReturnModel:
    quantiles = (0.10, 0.50, 0.90)

    def __init__(self, horizon: int = 5, random_seed: int = 20260718, **model_params: Any) -> None:
        validate_horizon(horizon)
        self.horizon = horizon
        self.random_seed = random_seed
        self.model_params = model_params
        self.models: dict[float, Any] = {}

    def fit(self, features: Any, gross_executable_returns: Sequence[float]) -> "QuantileReturnModel":
        try:
            model_class = import_module("lightgbm").LGBMRegressor
        except ModuleNotFoundError as error:
            raise RuntimeError("LightGBM is required to train QuantileReturnModel") from error
        for alpha in self.quantiles:
            parameters = {
                "objective": "quantile",
                "alpha": alpha,
                "random_state": self.random_seed,
            }
            parameters.update(self.model_params)
            model = model_class(**parameters)
            model.fit(features, gross_executable_returns)
            self.models[alpha] = model
        return self

    def predict_raw(self, features: Any) -> tuple[list[float], list[float], list[float]]:
        if set(self.models) != set(self.quantiles):
            raise RuntimeError("all three quantile models must be fitted")
        predictions = tuple(
            [float(value) for value in self.models[alpha].predict(features)] for alpha in self.quantiles
        )
        return predictions  # type: ignore[return-value]

    def predict(
        self,
        features: Any,
        round_trip_costs: float | Sequence[float],
        *,
        calibrator: IntervalCalibrator | None = None,
    ) -> list[QuantilePrediction]:
        q10s, q50s, q90s = self.predict_raw(features)
        if isinstance(round_trip_costs, (int, float)):
            costs = [float(round_trip_costs)] * len(q10s)
        else:
            costs = [float(value) for value in round_trip_costs]
        if len(costs) != len(q10s):
            raise ValueError("one round-trip cost is required per prediction")
        output: list[QuantilePrediction] = []
        for q10, q50, q90, cost in zip(q10s, q50s, q90s, costs):
            raw_crossed = is_crossed(q10, q50, q90)
            if calibrator is None:
                gross_q10, gross_q50, gross_q90 = reorder_quantiles(q10, q50, q90)
                calibration_status = "REORDERED_UNCALIBRATED" if raw_crossed else "UNCALIBRATED"
            else:
                gross_q10, gross_q50, gross_q90, _ = calibrator.transform_one(q10, q50, q90)
                calibration_status = f"CALIBRATED:{calibrator.version}"
            net = (gross_q10 - cost, gross_q50 - cost, gross_q90 - cost)
            output.append(
                QuantilePrediction(
                    gross_q10,
                    gross_q50,
                    gross_q90,
                    *net,
                    interval_width=net[2] - net[0],
                    raw_crossed=raw_crossed,
                    calibration_status=calibration_status,
                )
            )
        return output
