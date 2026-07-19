"""Coordinate independent model evaluations for one purged OOS fold."""

# pyright: reportAny=false

from __future__ import annotations

from dataclasses import dataclass

from src.calibration.interval_calibrator import IntervalCalibrator
from src.calibration.probability_calibrator import ProbabilityCalibrator
from src.data.preprocessing import CrossSectionalMedianImputer
from src.models.stock.direction_model import DirectionModel
from src.models.stock.quantile_return_model import QuantileReturnModel
from src.models.stock.rank_model import LGBMStockRanker
from src.validation.purged_walk_forward import PurgedFold

from .contracts import PipelineContext
from .research_dataset import PreparedResearchDataset
from .twse_research_fold_preparation import prepare_fold
from .twse_research_model_evaluation import (
    evaluate_direction,
    evaluate_quantiles,
    evaluate_rank,
)
from .twse_research_prediction_publisher import (
    FoldResearchPredictionBatch,
    build_fold_research_predictions,
)


@dataclass(frozen=True)
class TwseFoldFittedComponents:
    """Fitted state from one fold; never selected by test performance."""

    imputer: CrossSectionalMedianImputer
    rank_model: LGBMStockRanker
    direction_model: DirectionModel
    probability_calibrator: ProbabilityCalibrator
    quantile_model: QuantileReturnModel
    interval_calibrator: IntervalCalibrator


@dataclass(frozen=True)
class TwseFoldResearchResult:
    report: dict[str, object]
    prediction_batch: FoldResearchPredictionBatch
    fitted_components: TwseFoldFittedComponents


def evaluate_research_fold(
    dataset: PreparedResearchDataset,
    fold: PurgedFold,
    context: PipelineContext,
) -> TwseFoldResearchResult:
    """Fit preprocessing and all models within a single purged fold."""

    matrices = prepare_fold(
        dataset,
        train_indices=fold.train_indices,
        calibration_indices=fold.calibration_indices,
        test_indices=fold.test_indices,
        fold_number=fold.fold_number,
    )
    rank = evaluate_rank(
        frame=dataset.frame,
        train_indices=fold.train_indices,
        test_indices=fold.test_indices,
        matrices=matrices,
        context=context,
    )
    direction = evaluate_direction(
        frame=dataset.frame,
        train_indices=fold.train_indices,
        calibration_indices=fold.calibration_indices,
        test_indices=fold.test_indices,
        matrices=matrices,
        context=context,
    )
    quantiles = evaluate_quantiles(
        frame=dataset.frame,
        train_indices=fold.train_indices,
        calibration_indices=fold.calibration_indices,
        test_indices=fold.test_indices,
        matrices=matrices,
        context=context,
    )
    prediction_batch = build_fold_research_predictions(
        frame=dataset.frame,
        train_indices=fold.train_indices,
        test_indices=fold.test_indices,
        fold_number=fold.fold_number,
        rank=rank,
        direction=direction,
        quantiles=quantiles,
    )
    if (
        rank.fitted_model is None
        or direction.fitted_model is None
        or direction.fitted_calibrator is None
        or quantiles.fitted_model is None
        or quantiles.fitted_calibrator is None
    ):
        raise RuntimeError("fold evaluation did not retain all fitted components")
    return TwseFoldResearchResult(
        report={
            "fold_number": fold.fold_number,
            "train_dates": [value.isoformat() for value in fold.train_dates],
            "calibration_dates": [
                value.isoformat() for value in fold.calibration_dates
            ],
            "test_dates": [value.isoformat() for value in fold.test_dates],
            "train_rows": len(fold.train_indices),
            "calibration_rows": len(fold.calibration_indices),
            "test_rows": len(fold.test_indices),
            "ranking": rank.metrics,
            "direction": direction.metrics,
            "quantile": quantiles.metrics,
        },
        prediction_batch=prediction_batch,
        fitted_components=TwseFoldFittedComponents(
            imputer=matrices.imputer,
            rank_model=rank.fitted_model,
            direction_model=direction.fitted_model,
            probability_calibrator=direction.fitted_calibrator,
            quantile_model=quantiles.fitted_model,
            interval_calibrator=quantiles.fitted_calibrator,
        ),
    )


__all__ = [
    "TwseFoldFittedComponents",
    "TwseFoldResearchResult",
    "evaluate_research_fold",
]
