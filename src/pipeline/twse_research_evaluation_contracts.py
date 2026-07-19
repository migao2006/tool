"""Typed row-level outputs from independent OOS research model evaluations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RankEvaluation:
    metrics: dict[str, object]
    model_scores: tuple[float, ...]


@dataclass(frozen=True)
class DirectionEvaluation:
    metrics: dict[str, object]
    probabilities: tuple[tuple[float, float, float], ...]
    calibration_version: str


@dataclass(frozen=True)
class QuantileEvaluation:
    metrics: dict[str, object]
    gross_quantiles: tuple[tuple[float, float, float], ...]
    net_quantiles: tuple[tuple[float, float, float], ...]
    raw_crossed: tuple[bool, ...]
    calibration_version: str


__all__ = ["DirectionEvaluation", "QuantileEvaluation", "RankEvaluation"]
