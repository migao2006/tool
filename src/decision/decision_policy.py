"""Auditable decision gates; this module never creates a composite score."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from math import isclose
from typing import Any, Iterable, Mapping

from ..core.horizon import require_production_horizon, require_supported_horizon


class Decision(str, Enum):
    CANDIDATE = "CANDIDATE"
    WATCH = "WATCH"
    NO_TRADE = "NO_TRADE"


@dataclass(frozen=True)
class DecisionPolicyConfig:
    horizon: int = 5
    minimum_p_up: float = 0.55
    minimum_probability_spread: float = 0.15
    minimum_net_q50: float = 0.0
    maximum_net_q10_loss: float = 0.05
    top_k: int = 20
    maximum_adv_participation: float = 0.01

    def __post_init__(self) -> None:
        require_production_horizon(self.horizon)
        if not 0 <= self.minimum_p_up <= 1 or not 0 <= self.minimum_probability_spread <= 1:
            raise ValueError("probability thresholds must be between zero and one")
        if self.maximum_net_q10_loss < 0 or self.top_k <= 0:
            raise ValueError("risk limit and Top-K must be valid")
        if not 0 < self.maximum_adv_participation <= 1:
            raise ValueError("maximum ADV participation must be in (0, 1]")


@dataclass(frozen=True)
class GateResult:
    gate: str
    passed: bool
    actual: Any
    threshold: Any
    reason_code: str


@dataclass(frozen=True)
class DecisionResult:
    symbol: str
    horizon: int
    decision: Decision
    rank_score: float | None
    global_rank: int | None
    gates: tuple[GateResult, ...]
    reason_codes: tuple[str, ...]


def _gate(name: str, passed: bool, actual: Any, threshold: Any, fail_code: str) -> GateResult:
    return GateResult(name, passed, actual, threshold, "PASS" if passed else fail_code)


class DecisionPolicy:
    """Apply quality/risk gates, then allow rank-only Top-K selection."""

    def __init__(self, config: DecisionPolicyConfig | None = None) -> None:
        self.config = config or DecisionPolicyConfig()

    def evaluate(self, row: Mapping[str, Any]) -> DecisionResult:
        horizon = require_supported_horizon(int(row.get("horizon", self.config.horizon)))
        if horizon != self.config.horizon:
            raise ValueError("row horizon does not match decision policy artifact")

        quality_status = str(row.get("data_quality_status", "FAIL"))
        quality_pass = quality_status == "PASS" and not bool(row.get("data_quality_hard_fail", False))
        quality_gate = _gate("data_quality_hard_gate", quality_pass, quality_status, "PASS", "DATA_QUALITY_HARD_FAIL")

        tradable = bool(row.get("tradable", False))
        tradability_gate = _gate("tradability_gate", tradable, tradable, True, "NOT_TRADABLE")

        adv20_value = row.get("adv20_ntd", row.get("adv20"))
        order_notional_value = row.get("estimated_order_notional_ntd")
        adv20 = float(adv20_value or 0.0)
        order_notional = float(order_notional_value or 0.0)
        capacity = adv20 * self.config.maximum_adv_participation
        liquidity_pass = (
            bool(row.get("liquidity_pass", False))
            and adv20_value is not None
            and order_notional_value is not None
            and adv20 > 0
            and order_notional > 0
            and order_notional <= capacity
        )
        liquidity_gate = _gate(
            "liquidity_capacity_gate",
            liquidity_pass,
            {"adv20_ntd": adv20, "order_notional": order_notional},
            {"maximum_order_notional": capacity},
            "LIQUIDITY_OR_CAPACITY_FAIL",
        )

        exposure = float(row.get("market_exposure_cap", 0.0) or 0.0)
        market_gate = _gate("market_exposure_cap", exposure > 0, exposure, "> 0", "MARKET_EXPOSURE_ZERO")

        p_up = float(row.get("calibrated_p_up", -1.0))
        p_neutral = float(row.get("calibrated_p_neutral", -1.0))
        p_down = float(row.get("calibrated_p_down", -1.0))
        probability_sum_valid = all(value >= 0 for value in (p_up, p_neutral, p_down)) and isclose(
            p_up + p_neutral + p_down, 1.0, abs_tol=1e-6
        )
        direction_pass = (
            probability_sum_valid
            and p_up >= self.config.minimum_p_up
            and p_up - p_down >= self.config.minimum_probability_spread
        )
        direction_gate = _gate(
            "calibrated_direction_probabilities",
            direction_pass,
            {"p_up": p_up, "p_neutral": p_neutral, "p_down": p_down},
            {
                "minimum_p_up": self.config.minimum_p_up,
                "minimum_p_up_minus_p_down": self.config.minimum_probability_spread,
                "sum": 1.0,
            },
            "DIRECTION_THRESHOLD_FAIL" if probability_sum_valid else "INVALID_CALIBRATED_PROBABILITIES",
        )

        q10 = float(row.get("net_q10", float("-inf")))
        q50 = float(row.get("net_q50", float("-inf")))
        q90 = float(row.get("net_q90", float("-inf")))
        quantiles_monotonic = q10 <= q50 <= q90
        quantile_pass = (
            quantiles_monotonic
            and q50 > self.config.minimum_net_q50
            and q10 >= -self.config.maximum_net_q10_loss
        )
        quantile_gate = _gate(
            "net_quantile_thresholds",
            quantile_pass,
            {"net_q10": q10, "net_q50": q50, "net_q90": q90},
            {
                "minimum_net_q50": self.config.minimum_net_q50,
                "minimum_net_q10": -self.config.maximum_net_q10_loss,
                "monotonic": True,
            },
            "NET_QUANTILE_THRESHOLD_FAIL" if quantiles_monotonic else "NON_MONOTONIC_QUANTILES",
        )

        rank_score_value = row.get("rank_score")
        global_rank_value = row.get("global_rank")
        rank_valid = (
            rank_score_value is not None
            and global_rank_value is not None
            and 0 <= float(rank_score_value) <= 100
            and int(global_rank_value) > 0
        )
        rank_score = float(rank_score_value) if rank_score_value is not None else None
        global_rank = int(global_rank_value) if global_rank_value is not None else None
        rank_gate = _gate(
            "rank_eligibility", rank_valid, {"rank_score": rank_score, "global_rank": global_rank}, "present", "RANK_UNAVAILABLE"
        )

        position_limit_pass = bool(row.get("position_limits_pass", False))
        position_gate = _gate(
            "position_capacity_limits", position_limit_pass, position_limit_pass, True, "POSITION_LIMIT_FAIL"
        )

        gates = (
            quality_gate,
            tradability_gate,
            liquidity_gate,
            market_gate,
            direction_gate,
            quantile_gate,
            rank_gate,
            position_gate,
        )
        raw_source_reasons = row.get("reason_codes", ())
        source_reasons = (
            (str(raw_source_reasons),)
            if isinstance(raw_source_reasons, str)
            else tuple(str(code) for code in raw_source_reasons)
        )
        failed_codes = tuple(
            dict.fromkeys(
                (*source_reasons, *(gate.reason_code for gate in gates if not gate.passed))
            )
        )
        hard_or_trade_failure = any(not gate.passed for gate in gates[:6]) or not position_gate.passed
        if hard_or_trade_failure:
            decision = Decision.NO_TRADE
        elif not rank_gate.passed:
            decision = Decision.WATCH
        else:
            decision = Decision.CANDIDATE
        return DecisionResult(
            symbol=str(row["symbol"]),
            horizon=horizon,
            decision=decision,
            rank_score=rank_score,
            global_rank=global_rank,
            gates=gates,
            reason_codes=failed_codes,
        )

    def select_top_k(self, rows: Iterable[Mapping[str, Any]]) -> list[DecisionResult]:
        """Gate all rows, then retain Top-K using only rank_model output."""

        materialized = [dict(row) for row in rows]
        results = [self.evaluate(row) for row in materialized]
        by_date: dict[Any, list[DecisionResult]] = {}
        for row, result in zip(materialized, results):
            by_date.setdefault(row.get("decision_date"), []).append(result)
        retained: set[tuple[Any, str]] = set()
        for decision_date, date_results in by_date.items():
            eligible = sorted(
                (result for result in date_results if result.decision == Decision.CANDIDATE),
                key=lambda result: (
                    result.global_rank if result.global_rank is not None else float("inf"),
                    -(result.rank_score if result.rank_score is not None else float("-inf")),
                    result.symbol,
                ),
            )
            retained.update(
                (decision_date, result.symbol) for result in eligible[: self.config.top_k]
            )
        output: list[DecisionResult] = []
        for row, result in zip(materialized, results):
            key = (row.get("decision_date"), result.symbol)
            if result.decision == Decision.CANDIDATE and key not in retained:
                result = replace(
                    result,
                    decision=Decision.WATCH,
                    reason_codes=(*result.reason_codes, "OUTSIDE_TOP_K"),
                )
            output.append(result)
        return sorted(
            output,
            key=lambda result: (
                result.global_rank if result.global_rank is not None else float("inf"),
                result.symbol,
            ),
        )
