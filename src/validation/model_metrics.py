"""Direction and quantile metrics required by the MVP model card."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean
from typing import Mapping, Sequence


CLASSES = ("UP", "NEUTRAL", "DOWN")


def confusion_matrix(actual: Sequence[str], predicted: Sequence[str]) -> dict[str, dict[str, int]]:
    if len(actual) != len(predicted):
        raise ValueError("actual and predicted labels must have equal length")
    matrix = {label: {other: 0 for other in CLASSES} for label in CLASSES}
    for truth, estimate in zip(actual, predicted):
        if truth not in CLASSES or estimate not in CLASSES:
            raise ValueError(f"labels must be one of {CLASSES}")
        matrix[truth][estimate] += 1
    return matrix


def classwise_precision_recall_f1(
    actual: Sequence[str], predicted: Sequence[str]
) -> dict[str, dict[str, float]]:
    matrix = confusion_matrix(actual, predicted)
    output: dict[str, dict[str, float]] = {}
    for label in CLASSES:
        true_positive = matrix[label][label]
        predicted_positive = sum(matrix[truth][label] for truth in CLASSES)
        actual_positive = sum(matrix[label].values())
        precision = true_positive / predicted_positive if predicted_positive else 0.0
        recall = true_positive / actual_positive if actual_positive else 0.0
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        output[label] = {"precision": precision, "recall": recall, "f1": f1}
    return output


def macro_f1(actual: Sequence[str], predicted: Sequence[str]) -> float:
    metrics = classwise_precision_recall_f1(actual, predicted)
    return fmean(metrics[label]["f1"] for label in CLASSES)


@dataclass(frozen=True)
class ReliabilityBin:
    lower_bound: float
    upper_bound: float
    sample_count: int
    mean_probability: float | None
    observed_rate: float | None


def reliability_diagram(
    probabilities: Sequence[float], events: Sequence[bool], bins: int = 10
) -> tuple[ReliabilityBin, ...]:
    if len(probabilities) != len(events) or bins <= 0:
        raise ValueError("equal arrays and positive bins are required")
    grouped: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for probability, event in zip(probabilities, events):
        if not 0 <= probability <= 1:
            raise ValueError("probabilities must lie in [0, 1]")
        grouped[min(bins - 1, int(probability * bins))].append((float(probability), bool(event)))
    output: list[ReliabilityBin] = []
    for index, rows in enumerate(grouped):
        output.append(
            ReliabilityBin(
                lower_bound=index / bins,
                upper_bound=(index + 1) / bins,
                sample_count=len(rows),
                mean_probability=fmean(row[0] for row in rows) if rows else None,
                observed_rate=fmean(float(row[1]) for row in rows) if rows else None,
            )
        )
    return tuple(output)


def threshold_event_rate(
    p_up: Sequence[float], actual_labels: Sequence[str], threshold: float, tolerance: float = 0.025
) -> Mapping[str, float | int | None]:
    if len(p_up) != len(actual_labels) or tolerance < 0:
        raise ValueError("equal inputs and non-negative tolerance are required")
    selected = [
        (probability, label)
        for probability, label in zip(p_up, actual_labels)
        if abs(float(probability) - threshold) <= tolerance
    ]
    return {
        "sample_count": len(selected),
        "mean_predicted_p_up": fmean(item[0] for item in selected) if selected else None,
        "observed_up_rate": fmean(float(item[1] == "UP") for item in selected) if selected else None,
    }


def pinball_loss(actual: Sequence[float], predicted: Sequence[float], alpha: float) -> float:
    if len(actual) != len(predicted) or not actual or not 0 < alpha < 1:
        raise ValueError("pinball loss requires equal non-empty arrays and alpha in (0,1)")
    losses = []
    for truth, estimate in zip(actual, predicted):
        residual = float(truth) - float(estimate)
        losses.append(max(alpha * residual, (alpha - 1) * residual))
    return fmean(losses)


def quantile_coverage(
    actual: Sequence[float], q10: Sequence[float], q90: Sequence[float]
) -> dict[str, float]:
    if len({len(actual), len(q10), len(q90)}) != 1 or not actual:
        raise ValueError("quantile coverage requires equal non-empty arrays")
    count = len(actual)
    return {
        "p10_breach_rate": sum(float(truth) < float(lower) for truth, lower in zip(actual, q10)) / count,
        "p90_exceedance_rate": sum(float(truth) > float(upper) for truth, upper in zip(actual, q90)) / count,
        "p10_p90_coverage": sum(
            float(lower) <= float(truth) <= float(upper) for truth, lower, upper in zip(actual, q10, q90)
        )
        / count,
        "mean_interval_width": fmean(float(upper) - float(lower) for lower, upper in zip(q10, q90)),
    }
