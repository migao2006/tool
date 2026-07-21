"""Uncertainty estimates that respect overlapping forward-return dependence."""

from __future__ import annotations

from random import Random
from statistics import fmean
from typing import Sequence


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    index = round((len(ordered) - 1) * probability)
    return ordered[index]


def moving_block_bootstrap_mean(
    values: Sequence[float],
    block_length: int,
    samples: int = 2000,
    confidence: float = 0.95,
    seed: int = 20260718,
) -> tuple[float, float]:
    """Return a reproducible confidence interval for a dependent-series mean."""

    if not values or block_length <= 0 or block_length > len(values):
        raise ValueError("block length must fit within a non-empty series")
    if samples <= 0 or not 0 < confidence < 1:
        raise ValueError("samples and confidence must be valid")
    random = Random(seed)
    last_start = len(values) - block_length
    estimates: list[float] = []
    for _ in range(samples):
        draw: list[float] = []
        while len(draw) < len(values):
            start = random.randint(0, last_start)
            draw.extend(float(value) for value in values[start : start + block_length])
        estimates.append(fmean(draw[: len(values)]))
    tail = (1 - confidence) / 2
    return _quantile(estimates, tail), _quantile(estimates, 1 - tail)
