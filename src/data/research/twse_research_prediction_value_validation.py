"""Numeric contract checks for one research prediction JSON row."""

from __future__ import annotations

from collections.abc import Mapping
from math import isclose, isfinite
from typing import cast


def _required(payload: Mapping[str, object], name: str) -> object:
    value = payload.get(name)
    if value is None or value == "":
        raise ValueError(f"research prediction artifact is missing {name}")
    return value


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"research prediction {name} must be numeric")
    try:
        parsed = float(cast(float | int | str, value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"research prediction {name} must be numeric") from error
    if not isfinite(parsed):
        raise ValueError(f"research prediction {name} must be finite")
    return parsed


def validate_prediction_numbers(prediction: Mapping[str, object]) -> None:
    rank_score = _finite_number(_required(prediction, "rank_score"), "rank_score")
    rank_percentile = _finite_number(
        _required(prediction, "global_rank_percentile"),
        "global_rank_percentile",
    )
    if not 0 <= rank_score <= 100 or not 0 <= rank_percentile <= 1:
        raise ValueError("research prediction rank percentile is out of range")
    if not isclose(rank_score, 100 * rank_percentile, abs_tol=1e-4):
        raise ValueError("rank_score must equal 100 * global_rank_percentile")

    probabilities = tuple(
        _finite_number(_required(prediction, name), name)
        for name in ("calibrated_p_up", "calibrated_p_neutral", "calibrated_p_down")
    )
    if any(not 0 <= value <= 1 for value in probabilities) or not isclose(
        sum(probabilities), 1.0, abs_tol=1e-6
    ):
        raise ValueError(
            "calibrated probabilities must be within [0, 1] and sum to one"
        )

    gross = tuple(
        _finite_number(_required(prediction, name), name)
        for name in ("gross_q10", "gross_q50", "gross_q90")
    )
    net = tuple(
        _finite_number(_required(prediction, name), name)
        for name in ("net_q10", "net_q50", "net_q90")
    )
    if not gross[0] <= gross[1] <= gross[2] or not net[0] <= net[1] <= net[2]:
        raise ValueError("research prediction quantiles must be monotonic")
    interval_width = _finite_number(
        _required(prediction, "interval_width"), "interval_width"
    )
    if not isclose(interval_width, net[2] - net[0], abs_tol=1e-8):
        raise ValueError("interval_width must equal net_q90 - net_q10")
    if (
        _finite_number(
            _required(prediction, "estimated_round_trip_cost"),
            "estimated_round_trip_cost",
        )
        < 0
    ):
        raise ValueError("estimated_round_trip_cost must be non-negative")
    _ = _finite_number(_required(prediction, "model_raw_score"), "model_raw_score")


__all__ = ["validate_prediction_numbers"]
