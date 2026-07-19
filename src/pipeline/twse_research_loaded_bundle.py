"""Verified in-memory interface for TWSE research inference components."""

# pyright: reportAny=false, reportExplicitAny=false

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from src.calibration.interval_calibrator import IntervalCalibrator
from src.calibration.probability_calibrator import ProbabilityCalibrator
from src.data.preprocessing import CrossSectionalMedianImputer

from .twse_research_model_bundle_contracts import (
    TwseResearchModelBundleManifest,
)


@dataclass(frozen=True)
class CalibratedDirectionPrediction:
    up: float
    neutral: float
    down: float


@dataclass(frozen=True)
class CalibratedQuantilePrediction:
    gross_q10: float
    gross_q50: float
    gross_q90: float
    raw_crossed: bool


@dataclass(frozen=True)
class LoadedTwseResearchBundle:
    manifest: TwseResearchModelBundleManifest
    imputer: CrossSectionalMedianImputer
    rank_booster: Any
    direction_booster: Any
    quantile_boosters: tuple[Any, Any, Any]
    probability_calibrator: ProbabilityCalibrator
    interval_calibrator: IntervalCalibrator

    def transform(self, frame: Any, decision_dates: Sequence[date]) -> Any:
        """Apply the frozen fold-local imputer without fitting on inference data."""

        return self.imputer.transform_frame(frame, decision_dates=decision_dates)

    def predict_rank(self, matrix: Any) -> tuple[float, ...]:
        return tuple(float(value) for value in self.rank_booster.predict(matrix))

    def predict_direction(
        self, matrix: Any
    ) -> tuple[CalibratedDirectionPrediction, ...]:
        raw = np.asarray(self.direction_booster.predict(matrix), dtype=np.float64)
        if raw.ndim != 2 or raw.shape[1] != len(self.manifest.direction_classes):
            raise ValueError("direction booster output does not match saved classes")
        positions = {
            class_name: index
            for index, class_name in enumerate(self.manifest.direction_classes)
        }
        named = [
            {class_name: float(row[position]) for class_name, position in positions.items()}
            for row in raw
        ]
        calibrated = self.probability_calibrator.transform_rows(named)
        return tuple(
            CalibratedDirectionPrediction(*map(float, row)) for row in calibrated
        )

    def predict_quantiles(
        self, matrix: Any
    ) -> tuple[CalibratedQuantilePrediction, ...]:
        raw = tuple(
            [float(value) for value in booster.predict(matrix)]
            for booster in self.quantile_boosters
        )
        calibrated = self.interval_calibrator.transform(*raw)
        return tuple(
            CalibratedQuantilePrediction(
                gross_q10=float(row[0]),
                gross_q50=float(row[1]),
                gross_q90=float(row[2]),
                raw_crossed=bool(row[3]),
            )
            for row in calibrated
        )


__all__ = [
    "CalibratedDirectionPrediction",
    "CalibratedQuantilePrediction",
    "LoadedTwseResearchBundle",
]
