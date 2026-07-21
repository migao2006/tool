"""Dependency-free per-date ranking metrics."""

from __future__ import annotations

from math import log2, sqrt
from statistics import fmean, pstdev
from typing import Sequence


def ndcg_at_k(relevance: Sequence[float], predicted_scores: Sequence[float], k: int) -> float:
    if len(relevance) != len(predicted_scores) or k <= 0:
        raise ValueError("equal arrays and a positive K are required")
    if not relevance:
        return 0.0
    order = sorted(range(len(relevance)), key=lambda index: (-float(predicted_scores[index]), index))[:k]
    ideal = sorted(range(len(relevance)), key=lambda index: -float(relevance[index]))[:k]

    def dcg(indices: Sequence[int]) -> float:
        return sum((2 ** float(relevance[index]) - 1) / log2(position + 2) for position, index in enumerate(indices))

    ideal_dcg = dcg(ideal)
    return 0.0 if ideal_dcg == 0 else dcg(order) / ideal_dcg


def precision_at_k(
    realized_alpha: Sequence[float], predicted_scores: Sequence[float], k: int, positive_threshold: float = 0.0
) -> float:
    if len(realized_alpha) != len(predicted_scores) or k <= 0:
        raise ValueError("equal arrays and a positive K are required")
    selected = sorted(range(len(predicted_scores)), key=lambda index: -float(predicted_scores[index]))[:k]
    return 0.0 if not selected else sum(float(realized_alpha[index]) > positive_threshold for index in selected) / len(selected)


def _average_ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: (float(values[index]), index))
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        while end < len(order) and float(values[order[end]]) == float(values[order[cursor]]):
            end += 1
        average = (cursor + end - 1) / 2
        for position in range(cursor, end):
            ranks[order[position]] = average
        cursor = end
    return ranks


def spearman_rank_ic(realized_alpha: Sequence[float], predicted_scores: Sequence[float]) -> float:
    if len(realized_alpha) != len(predicted_scores) or len(realized_alpha) < 2:
        raise ValueError("Spearman Rank IC requires equal arrays with at least two observations")
    left = _average_ranks(realized_alpha)
    right = _average_ranks(predicted_scores)
    left_mean = fmean(left)
    right_mean = fmean(right)
    covariance = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_scale = sqrt(sum((value - left_mean) ** 2 for value in left))
    right_scale = sqrt(sum((value - right_mean) ** 2 for value in right))
    return 0.0 if left_scale == 0 or right_scale == 0 else covariance / (left_scale * right_scale)


def ic_information_ratio(daily_rank_ic: Sequence[float]) -> float:
    if not daily_rank_ic:
        raise ValueError("daily Rank IC cannot be empty")
    standard_deviation = pstdev(daily_rank_ic)
    return 0.0 if standard_deviation == 0 else fmean(daily_rank_ic) / standard_deviation
