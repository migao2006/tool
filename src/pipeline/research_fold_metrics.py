"""Small, serializable metric summaries for research walk-forward folds."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import fmean

from src.calibration.probability_calibrator import (
    classwise_brier_score,
    expected_calibration_error,
    multiclass_log_loss,
)
from src.validation.model_metrics import (
    macro_f1,
    pinball_loss,
    quantile_coverage,
    threshold_event_rate,
)
from src.validation.ranking_metrics import (
    ic_information_ratio,
    ndcg_at_k,
    precision_at_k,
    spearman_rank_ic,
)


def ranking_metric_summary(
    *,
    decision_dates: Sequence[object],
    realized_alpha: Sequence[float],
    relevance: Sequence[int],
    predicted_scores: Sequence[float],
    eval_at: Sequence[int],
) -> dict[str, float]:
    lengths = {
        len(decision_dates),
        len(realized_alpha),
        len(relevance),
        len(predicted_scores),
    }
    if len(lengths) != 1 or not decision_dates:
        raise ValueError("ranking metrics require equal non-empty inputs")
    groups: dict[object, list[int]] = defaultdict(list)
    for index, decision_date in enumerate(decision_dates):
        groups[decision_date].append(index)

    ndcg: dict[int, list[float]] = {int(k): [] for k in eval_at}
    precision: dict[int, list[float]] = {int(k): [] for k in eval_at}
    daily_ic: list[float] = []
    for indices in groups.values():
        actual = [float(realized_alpha[index]) for index in indices]
        grades = [int(relevance[index]) for index in indices]
        scores = [float(predicted_scores[index]) for index in indices]
        for k in eval_at:
            ndcg[int(k)].append(ndcg_at_k(grades, scores, int(k)))
            precision[int(k)].append(precision_at_k(actual, scores, int(k)))
        if len(indices) >= 2:
            daily_ic.append(spearman_rank_ic(actual, scores))

    output = {
        **{f"ndcg_at_{k}": fmean(values) for k, values in ndcg.items()},
        **{f"precision_at_{k}": fmean(values) for k, values in precision.items()},
        "rank_ic_mean": fmean(daily_ic) if daily_ic else 0.0,
        "rank_icir": ic_information_ratio(daily_ic) if daily_ic else 0.0,
        "evaluated_dates": float(len(groups)),
    }
    return output


def direction_metric_summary(
    *,
    actual: Sequence[str],
    probabilities: Sequence[Sequence[float]],
    p_up_threshold: float,
) -> dict[str, object]:
    if len(actual) != len(probabilities) or not actual:
        raise ValueError("direction metrics require equal non-empty inputs")
    predictions = [
        ("UP", "NEUTRAL", "DOWN")[max(range(3), key=lambda index: float(row[index]))]
        for row in probabilities
    ]
    p_up = [float(row[0]) for row in probabilities]
    return {
        "log_loss": multiclass_log_loss(probabilities, actual),
        "macro_f1": macro_f1(actual, predictions),
        "classwise_brier": classwise_brier_score(probabilities, actual),
        "ece": expected_calibration_error(probabilities, actual),
        "threshold_event_rate": dict(
            threshold_event_rate(p_up, actual, threshold=p_up_threshold)
        ),
    }


def quantile_metric_summary(
    *,
    actual: Sequence[float],
    q10: Sequence[float],
    q50: Sequence[float],
    q90: Sequence[float],
    raw_crossing_rate: float,
) -> dict[str, object]:
    return {
        "pinball_q10": pinball_loss(actual, q10, 0.10),
        "pinball_q50": pinball_loss(actual, q50, 0.50),
        "pinball_q90": pinball_loss(actual, q90, 0.90),
        "coverage": quantile_coverage(actual, q10, q90),
        "raw_crossing_rate": float(raw_crossing_rate),
        "final_crossing_rate": 0.0,
    }


def mean_scalar_metrics(
    fold_metrics: Sequence[Mapping[str, object]],
) -> dict[str, float]:
    """Average only numeric top-level metrics without flattening nested audits."""

    keys = {
        key
        for metrics in fold_metrics
        for key, value in metrics.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    output: dict[str, float] = {}
    for key in sorted(keys):
        values: list[float] = []
        for metrics in fold_metrics:
            value = metrics.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(float(value))
        if values:
            output[key] = fmean(values)
    return output
