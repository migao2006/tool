"""Out-of-sample additive quantile calibration and crossing audit."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Hashable, Iterable, Sequence


def _empirical_quantile(values: Sequence[float], alpha: float) -> float:
    if not values:
        raise ValueError("calibration values cannot be empty")
    if not 0 <= alpha <= 1:
        raise ValueError("alpha must be between zero and one")
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, ceil(alpha * len(ordered)) - 1))
    return ordered[index]


def is_crossed(q10: float, q50: float, q90: float) -> bool:
    return q10 > q50 or q50 > q90


def crossing_rate(rows: Iterable[Sequence[float]]) -> float:
    materialized = [tuple(float(value) for value in row) for row in rows]
    if not materialized:
        return 0.0
    return sum(is_crossed(*row) for row in materialized) / len(materialized)


def reorder_quantiles(q10: float, q50: float, q90: float) -> tuple[float, float, float]:
    ordered = sorted((float(q10), float(q50), float(q90)))
    return ordered[0], ordered[1], ordered[2]


@dataclass(frozen=True)
class IntervalCalibrationAudit:
    raw_crossing_rate: float
    calibrated_crossing_rate: float
    calibration_size: int


class IntervalCalibrator:
    """Calibrate each predicted quantile from an untouched time block."""

    alphas = (0.10, 0.50, 0.90)

    def __init__(self, version: str = "interval-calibration-v1") -> None:
        self.version = version
        self.offsets: tuple[float, float, float] | None = None
        self.audit: IntervalCalibrationAudit | None = None

    def fit(
        self,
        y_true: Sequence[float],
        q10: Sequence[float],
        q50: Sequence[float],
        q90: Sequence[float],
        *,
        calibration_ids: Sequence[Hashable] | None = None,
        base_training_ids: Iterable[Hashable] | None = None,
    ) -> "IntervalCalibrator":
        lengths = {len(y_true), len(q10), len(q50), len(q90)}
        if len(lengths) != 1 or not y_true:
            raise ValueError("all non-empty calibration arrays must have equal length")
        if calibration_ids is None or base_training_ids is None:
            raise ValueError("calibration IDs and base-training IDs are required")
        if len(calibration_ids) != len(y_true):
            raise ValueError("one calibration ID is required per row")
        if set(calibration_ids).intersection(base_training_ids):
            raise ValueError("base-model training and calibration samples must be disjoint")
        raw_rows = list(zip(q10, q50, q90))
        residuals = [
            [float(actual) - float(predicted) for actual, predicted in zip(y_true, predictions)]
            for predictions in (q10, q50, q90)
        ]
        self.offsets = tuple(
            _empirical_quantile(residual, alpha) for residual, alpha in zip(residuals, self.alphas)
        )
        calibrated = [self.transform_one(*row)[:3] for row in raw_rows]
        self.audit = IntervalCalibrationAudit(
            raw_crossing_rate=crossing_rate(raw_rows),
            calibrated_crossing_rate=crossing_rate(calibrated),
            calibration_size=len(y_true),
        )
        return self

    def transform_one(self, q10: float, q50: float, q90: float) -> tuple[float, float, float, bool]:
        if self.offsets is None:
            raise RuntimeError("interval calibrator has not been fitted")
        raw_crossed = is_crossed(q10, q50, q90)
        shifted = tuple(value + offset for value, offset in zip((q10, q50, q90), self.offsets))
        return (*reorder_quantiles(*shifted), raw_crossed)

    def transform(
        self, q10: Sequence[float], q50: Sequence[float], q90: Sequence[float]
    ) -> list[tuple[float, float, float, bool]]:
        if len({len(q10), len(q50), len(q90)}) != 1:
            raise ValueError("quantile arrays must have equal length")
        return [self.transform_one(*row) for row in zip(q10, q50, q90)]
