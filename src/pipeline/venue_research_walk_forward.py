"""Venue-neutral purged walk-forward fold construction and evaluation."""

# pyright: reportAny=false, reportExplicitAny=false

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from src.validation.purged_walk_forward import (
    PurgedFold,
    PurgedWalkForwardSplitter,
    locked_holdout_split,
)

from .contracts import PipelineContext
from .research_dataset import PreparedResearchDataset
from .research_fold_metrics import mean_scalar_metrics
from .twse_research_fold_runner import TwseFoldResearchResult, evaluate_research_fold
from .twse_research_prediction_publisher import FoldResearchPredictionBatch


TRADING_DAYS_PER_YEAR = 252
TRADING_DAYS_PER_MONTH = 21


class WalkForwardBlocked(RuntimeError):
    """Expected, fail-closed inability to create a valid validation window."""

    def __init__(
        self,
        reason_code: str,
        *,
        metrics: dict[str, object] | None = None,
    ) -> None:
        super().__init__(reason_code)
        self.reason_code: str = reason_code
        self.metrics: dict[str, object] = metrics or {}


@dataclass(frozen=True)
class WalkForwardEvaluation:
    reports: tuple[dict[str, object], ...]
    prediction_batches: tuple[FoldResearchPredictionBatch, ...]
    last_fold: PurgedFold
    last_fold_result: TwseFoldResearchResult
    metrics: dict[str, object]


def evaluate_walk_forward(
    dataset: PreparedResearchDataset,
    context: PipelineContext,
    *,
    market: str,
    feature_schema_hash: str,
    fold_scope_prefix: str,
    scope: str,
) -> WalkForwardEvaluation:
    """Build holdout and purged folds, then fit all independent models."""

    holdout_dates = (
        context.config.validation.locked_holdout_months * TRADING_DAYS_PER_MONTH
    )
    try:
        development_indices, holdout_indices = locked_holdout_split(
            dataset.observations(),
            holdout_trading_dates=holdout_dates,
            purge_trading_dates=context.config.validation.purge_trading_days,
        )
    except ValueError as error:
        raise WalkForwardBlocked("INSUFFICIENT_LOCKED_HOLDOUT_HISTORY") from error

    development = PreparedResearchDataset.from_frame(
        dataset.frame.iloc[list(development_indices)].copy(),
        feature_names=dataset.feature_names,
        horizon=context.horizon,
        market=market,
        feature_schema_hash=feature_schema_hash,
    )
    splitter = PurgedWalkForwardSplitter(
        minimum_train_dates=(
            context.config.validation.minimum_training_years * TRADING_DAYS_PER_YEAR
        ),
        calibration_dates=(
            context.config.validation.calibration_months * TRADING_DAYS_PER_MONTH
        ),
        test_dates=context.config.validation.test_months * TRADING_DAYS_PER_MONTH,
        purge_trading_dates=context.config.validation.purge_trading_days,
        step_dates=context.config.validation.step_months * TRADING_DAYS_PER_MONTH,
    )
    folds = tuple(splitter.split(development.observations()))
    if not folds:
        raise WalkForwardBlocked(
            "INSUFFICIENT_WALK_FORWARD_HISTORY",
            metrics={
                "locked_holdout_executed": False,
                "locked_holdout_rows": len(holdout_indices),
            },
        )

    results = tuple(
        evaluate_research_fold(
            development,
            fold,
            context,
            fold_scope_prefix=fold_scope_prefix,
        )
        for fold in folds
    )
    reports = tuple(result.report for result in results)
    ranking_primary: list[Mapping[str, object]] = []
    for report in reports:
        ranking_section = report.get("ranking")
        if not isinstance(ranking_section, Mapping):
            raise RuntimeError("ranking fold report is invalid")
        model_section = cast(Mapping[str, object], ranking_section).get("model")
        if not isinstance(model_section, Mapping):
            raise RuntimeError("ranking model fold report is invalid")
        ranking_primary.append(cast(Mapping[str, object], model_section))

    return WalkForwardEvaluation(
        reports=reports,
        prediction_batches=tuple(result.prediction_batch for result in results),
        last_fold=folds[-1],
        last_fold_result=results[-1],
        metrics={
            "system_status": "RESEARCH_ONLY",
            "market": market,
            "scope": scope,
            "fold_count": len(reports),
            "walk_forward": reports,
            "ranking_mean": mean_scalar_metrics(ranking_primary),
            "locked_holdout_executed": False,
            "locked_holdout_rows": len(holdout_indices),
            "locked_holdout_reason": "FROZEN_UNTIL_RESEARCH_DESIGN_IS_LOCKED",
        },
    )


__all__ = [
    "WalkForwardBlocked",
    "WalkForwardEvaluation",
    "evaluate_walk_forward",
]
