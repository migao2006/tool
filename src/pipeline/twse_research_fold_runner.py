"""Coordinate independent model evaluations for one purged OOS fold."""

# pyright: reportAny=false

from __future__ import annotations

from dataclasses import dataclass

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
class TwseFoldResearchResult:
    report: dict[str, object]
    prediction_batch: FoldResearchPredictionBatch


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
    )


__all__ = ["TwseFoldResearchResult", "evaluate_research_fold"]
