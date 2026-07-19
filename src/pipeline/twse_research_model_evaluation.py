"""Fold-level ranking, direction, and quantile evaluation."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from src.calibration.interval_calibrator import IntervalCalibrator, crossing_rate
from src.calibration.probability_calibrator import ProbabilityCalibrator
from src.models.stock.direction_model import DirectionModel
from src.models.stock.quantile_return_model import QuantileReturnModel
from src.models.stock.rank_model import (
    LGBMStockRanker,
    RankingConfig,
    RegressThenRankBaseline,
    make_relevance_labels,
    random_baseline_scores,
)

from .contracts import PipelineContext
from .research_fold_metrics import (
    direction_metric_summary,
    quantile_metric_summary,
    ranking_metric_summary,
)
from .twse_research_fold_preparation import (
    FoldMatrices,
    frame_dates,
)


def rank_metrics(
    *,
    frame: Any,
    train_indices: Sequence[int],
    test_indices: Sequence[int],
    matrices: FoldMatrices,
    context: PipelineContext,
) -> dict[str, object]:
    """Evaluate LambdaRank against the fixed baseline suite."""

    train_dates = frame_dates(frame, train_indices)
    test_dates = frame_dates(frame, test_indices)
    train_alpha = [
        float(value) for value in frame.iloc[list(train_indices)]["net_alpha"]
    ]
    test_alpha = [float(value) for value in frame.iloc[list(test_indices)]["net_alpha"]]
    train_relevance = make_relevance_labels(train_dates, train_alpha)
    test_relevance = make_relevance_labels(test_dates, test_alpha)
    ranker = LGBMStockRanker(
        RankingConfig(
            horizon=context.horizon,
            relevance_levels=context.config.rank.relevance_levels,
            eval_at=context.config.rank.eval_at,
            lambdarank_truncation_level=(
                context.config.rank.lambdarank_truncation_level
            ),
            random_seed=context.config.rank.seed,
        ),
        verbosity=-1,
    ).fit(matrices.train, train_relevance, train_dates)
    model_scores = ranker.predict(matrices.test)
    primary = ranking_metric_summary(
        decision_dates=test_dates,
        realized_alpha=test_alpha,
        relevance=test_relevance,
        predicted_scores=model_scores,
        eval_at=context.config.rank.eval_at,
    )

    sample_ids = [
        f"{row.symbol}:{row.decision_date.isoformat()}"
        for row in frame.iloc[list(test_indices)].itertuples()
    ]
    baselines: dict[str, dict[str, float]] = {}
    baseline_scores: dict[str, Sequence[float]] = {
        "random": random_baseline_scores(sample_ids, seed=context.config.rank.seed),
        "momentum_5d": [
            float(value)
            for value in frame.iloc[list(test_indices)]["raw_close_return_5d"]
        ],
        "momentum_20d": [
            float(value)
            for value in frame.iloc[list(test_indices)]["raw_close_return_20d"]
        ],
    }
    for backend in ("linear", "lightgbm"):
        estimator = RegressThenRankBaseline(
            backend=backend,
            random_seed=context.config.rank.seed,
        ).fit(matrices.train, train_alpha)
        baseline_scores[f"regress_then_rank_{backend}"] = estimator.predict(
            matrices.test
        )
    for name, scores in baseline_scores.items():
        baselines[name] = ranking_metric_summary(
            decision_dates=test_dates,
            realized_alpha=test_alpha,
            relevance=test_relevance,
            predicted_scores=scores,
            eval_at=context.config.rank.eval_at,
        )
    return {"model": primary, "baselines": baselines}


def direction_metrics(
    *,
    frame: Any,
    train_indices: Sequence[int],
    calibration_indices: Sequence[int],
    test_indices: Sequence[int],
    matrices: FoldMatrices,
    context: PipelineContext,
) -> dict[str, object]:
    """Train the direction candidate and calibrate on a disjoint time slice."""

    train_labels = list(frame.iloc[list(train_indices)]["direction"])
    calibration_labels = list(frame.iloc[list(calibration_indices)]["direction"])
    test_labels = list(frame.iloc[list(test_indices)]["direction"])
    model = DirectionModel(
        horizon=context.horizon,
        backend="lightgbm",
        random_seed=context.config.rank.seed,
        verbosity=-1,
    ).fit(matrices.train, train_labels)
    calibration_raw = model.predict_raw_proba(matrices.calibration)
    train_ids = [
        f"{row.symbol}:{row.decision_date.isoformat()}"
        for row in frame.iloc[list(train_indices)].itertuples()
    ]
    calibration_ids = [
        f"{row.symbol}:{row.decision_date.isoformat()}"
        for row in frame.iloc[list(calibration_indices)].itertuples()
    ]
    calibrator = ProbabilityCalibrator(method="temperature").fit(
        calibration_raw,
        calibration_labels,
        calibration_ids=calibration_ids,
        base_training_ids=train_ids,
    )
    probabilities = calibrator.transform_rows(model.predict_raw_proba(matrices.test))
    summary = direction_metric_summary(
        actual=test_labels,
        probabilities=probabilities,
        p_up_threshold=context.config.decision.minimum_p_up,
    )
    assert calibrator.audit is not None
    summary["calibration"] = {
        "method": calibrator.audit.method,
        "calibration_size": calibrator.audit.calibration_size,
        "uncalibrated_log_loss": calibrator.audit.uncalibrated_log_loss,
        "calibrated_log_loss": calibrator.audit.calibrated_log_loss,
    }
    return summary


def quantile_metrics(
    *,
    frame: Any,
    train_indices: Sequence[int],
    calibration_indices: Sequence[int],
    test_indices: Sequence[int],
    matrices: FoldMatrices,
    context: PipelineContext,
) -> dict[str, object]:
    """Train gross-return quantiles and evaluate calibrated net intervals."""

    train_gross = [
        float(value) for value in frame.iloc[list(train_indices)]["gross_return"]
    ]
    calibration_gross = [
        float(value) for value in frame.iloc[list(calibration_indices)]["gross_return"]
    ]
    model = QuantileReturnModel(
        horizon=context.horizon,
        random_seed=context.config.rank.seed,
        verbosity=-1,
    ).fit(matrices.train, train_gross)
    calibration_raw = model.predict_raw(matrices.calibration)
    train_ids = [
        f"{row.symbol}:{row.decision_date.isoformat()}"
        for row in frame.iloc[list(train_indices)].itertuples()
    ]
    calibration_ids = [
        f"{row.symbol}:{row.decision_date.isoformat()}"
        for row in frame.iloc[list(calibration_indices)].itertuples()
    ]
    calibrator = IntervalCalibrator().fit(
        calibration_gross,
        *calibration_raw,
        calibration_ids=calibration_ids,
        base_training_ids=train_ids,
    )
    raw_test = model.predict_raw(matrices.test)
    calibrated = calibrator.transform(*raw_test)
    costs = [
        float(value) for value in frame.iloc[list(test_indices)]["round_trip_cost_rate"]
    ]
    q10 = [row[0] - cost for row, cost in zip(calibrated, costs)]
    q50 = [row[1] - cost for row, cost in zip(calibrated, costs)]
    q90 = [row[2] - cost for row, cost in zip(calibrated, costs)]
    actual_net = [
        float(value) for value in frame.iloc[list(test_indices)]["net_return"]
    ]
    summary = quantile_metric_summary(
        actual=actual_net,
        q10=q10,
        q50=q50,
        q90=q90,
        raw_crossing_rate=crossing_rate(zip(*raw_test)),
    )
    assert calibrator.audit is not None
    summary["calibration"] = {
        "calibration_size": calibrator.audit.calibration_size,
        "raw_crossing_rate": calibrator.audit.raw_crossing_rate,
        "calibrated_crossing_rate": calibrator.audit.calibrated_crossing_rate,
    }
    return summary
