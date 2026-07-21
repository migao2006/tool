"""Typed row-level outputs from independent OOS research model evaluations."""

from __future__ import annotations

from dataclasses import dataclass

from src.calibration.interval_calibrator import IntervalCalibrator
from src.calibration.probability_calibrator import ProbabilityCalibrator
from src.models.stock.direction_model import DirectionModel
from src.models.stock.quantile_return_model import QuantileReturnModel
from src.models.stock.rank_model import LGBMStockRanker


@dataclass(frozen=True)
class RankEvaluation:
    metrics: dict[str, object]
    model_scores: tuple[float, ...]
    fitted_model: LGBMStockRanker | None = None


@dataclass(frozen=True)
class DirectionEvaluation:
    metrics: dict[str, object]
    probabilities: tuple[tuple[float, float, float], ...]
    calibration_version: str
    fitted_model: DirectionModel | None = None
    fitted_calibrator: ProbabilityCalibrator | None = None


@dataclass(frozen=True)
class QuantileEvaluation:
    metrics: dict[str, object]
    gross_quantiles: tuple[tuple[float, float, float], ...]
    net_quantiles: tuple[tuple[float, float, float], ...]
    raw_crossed: tuple[bool, ...]
    calibration_version: str
    fitted_model: QuantileReturnModel | None = None
    fitted_calibrator: IntervalCalibrator | None = None


__all__ = ["DirectionEvaluation", "QuantileEvaluation", "RankEvaluation"]
