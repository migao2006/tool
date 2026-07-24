"""Auditable decision gates; this module never creates a composite score."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from math import isclose, isfinite
from typing import Any, Iterable, Mapping

from ..calibration.status import (
    has_calibrated_interval_status,
    has_valid_calibration_version,
)
from ..core.horizon import require_production_horizon, require_supported_horizon


DECISION_GATE_ORDER = (
    "data_quality_hard_gate",
    "tradability_gate",
    "liquidity_capacity_gate",
    "market_exposure_cap",
    "calibrated_direction_probabilities",
    "net_quantile_thresholds",
    "rank_eligibility",
    "position_capacity_limits",
)


class Decision(str, Enum):
    CANDIDATE = "CANDIDATE"
    WATCH = "WATCH"
    NO_TRADE = "NO_TRADE"


class DecisionPolicyStatus(str, Enum):
    """Whether a policy action was formed from complete, valid evidence."""

    EVALUATED = "EVALUATED"
    MISSING_REQUIRED_DATA = "MISSING_REQUIRED_DATA"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    HARD_FAIL = "HARD_FAIL"


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
    policy_status: DecisionPolicyStatus = DecisionPolicyStatus.EVALUATED


@dataclass(frozen=True)
class DecisionResult:
    symbol: str
    horizon: int
    decision: Decision | None
    decision_policy_status: DecisionPolicyStatus
    rank_score: float | None
    global_rank: int | None
    gates: tuple[GateResult, ...]
    reason_codes: tuple[str, ...]


_MISSING = object()
_STATUS_PRIORITY = {
    DecisionPolicyStatus.EVALUATED: 0,
    DecisionPolicyStatus.VALIDATION_FAILED: 1,
    DecisionPolicyStatus.MISSING_REQUIRED_DATA: 2,
    DecisionPolicyStatus.HARD_FAIL: 3,
}


def _gate(
    name: str,
    passed: bool,
    actual: Any,
    threshold: Any,
    fail_code: str,
    *,
    policy_status: DecisionPolicyStatus = DecisionPolicyStatus.EVALUATED,
) -> GateResult:
    return GateResult(
        name,
        passed,
        actual,
        threshold,
        "PASS" if passed else fail_code,
        DecisionPolicyStatus.EVALUATED if passed else policy_status,
    )


def _raw_value(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return _MISSING


def _number(value: Any) -> tuple[float | None, DecisionPolicyStatus]:
    if value is _MISSING or value is None:
        return None, DecisionPolicyStatus.MISSING_REQUIRED_DATA
    if isinstance(value, bool):
        return None, DecisionPolicyStatus.VALIDATION_FAILED
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None, DecisionPolicyStatus.VALIDATION_FAILED
    if not isfinite(parsed):
        return None, DecisionPolicyStatus.VALIDATION_FAILED
    return parsed, DecisionPolicyStatus.EVALUATED


def _valid_probability_vector(
    values: tuple[float | None, float | None, float | None],
) -> bool:
    if any(value is None for value in values):
        return False
    present = tuple(value for value in values if value is not None)
    return all(0 <= value <= 1 for value in present) and isclose(sum(present), 1.0, abs_tol=1e-6)


def _highest_status(gates: tuple[GateResult, ...]) -> DecisionPolicyStatus:
    return max(
        (gate.policy_status for gate in gates),
        key=_STATUS_PRIORITY.__getitem__,
    )


class DecisionPolicy:
    """Apply quality/risk gates, then allow rank-only Top-K selection."""

    def __init__(self, config: DecisionPolicyConfig | None = None) -> None:
        self.config = config or DecisionPolicyConfig()

    def evaluate(self, row: Mapping[str, Any]) -> DecisionResult:
        horizon = require_supported_horizon(int(row.get("horizon", self.config.horizon)))
        if horizon != self.config.horizon:
            raise ValueError("row horizon does not match decision policy artifact")

        quality_value = _raw_value(row, "data_quality_status")
        hard_fail_value = _raw_value(row, "data_quality_hard_fail")
        quality_status = (
            quality_value.strip().upper() if isinstance(quality_value, str) else quality_value
        )
        if quality_value is _MISSING or hard_fail_value is _MISSING:
            quality_gate = _gate(
                "data_quality_hard_gate",
                False,
                "MISSING",
                "PASS",
                "DATA_QUALITY_INPUT_MISSING",
                policy_status=DecisionPolicyStatus.MISSING_REQUIRED_DATA,
            )
        elif not isinstance(hard_fail_value, bool) or not isinstance(quality_status, str):
            quality_gate = _gate(
                "data_quality_hard_gate",
                False,
                quality_status,
                "PASS",
                "DATA_QUALITY_INPUT_INVALID",
                policy_status=DecisionPolicyStatus.VALIDATION_FAILED,
            )
        elif hard_fail_value or quality_status in {"FAIL", "HARD_FAIL"}:
            quality_gate = _gate(
                "data_quality_hard_gate",
                False,
                quality_status,
                "PASS",
                "DATA_QUALITY_HARD_FAIL",
                policy_status=DecisionPolicyStatus.HARD_FAIL,
            )
        elif quality_status == "WARN":
            quality_gate = _gate(
                "data_quality_hard_gate",
                False,
                quality_status,
                "PASS",
                "DATA_QUALITY_NOT_FORMALLY_VERIFIED",
                policy_status=DecisionPolicyStatus.VALIDATION_FAILED,
            )
        elif quality_status == "PASS":
            quality_gate = _gate(
                "data_quality_hard_gate",
                True,
                quality_status,
                "PASS",
                "DATA_QUALITY_HARD_FAIL",
            )
        else:
            quality_gate = _gate(
                "data_quality_hard_gate",
                False,
                quality_status,
                "PASS",
                "DATA_QUALITY_INPUT_INVALID",
                policy_status=DecisionPolicyStatus.VALIDATION_FAILED,
            )

        tradable_value = _raw_value(row, "tradable")
        if tradable_value is _MISSING or tradable_value is None:
            tradability_gate = _gate(
                "tradability_gate",
                False,
                "MISSING",
                True,
                "TRADABILITY_INPUT_MISSING",
                policy_status=DecisionPolicyStatus.MISSING_REQUIRED_DATA,
            )
        elif not isinstance(tradable_value, bool):
            tradability_gate = _gate(
                "tradability_gate",
                False,
                tradable_value,
                True,
                "TRADABILITY_INPUT_INVALID",
                policy_status=DecisionPolicyStatus.VALIDATION_FAILED,
            )
        else:
            tradability_gate = _gate(
                "tradability_gate",
                tradable_value,
                tradable_value,
                True,
                "NOT_TRADABLE",
            )

        liquidity_value = _raw_value(row, "liquidity_pass")
        adv20_value = _raw_value(row, "adv20_ntd", "adv20")
        order_notional_value = _raw_value(row, "estimated_order_notional_ntd")
        adv20, adv20_status = _number(adv20_value)
        order_notional, order_status = _number(order_notional_value)
        liquidity_missing = (
            liquidity_value is _MISSING
            or liquidity_value is None
            or adv20_status == DecisionPolicyStatus.MISSING_REQUIRED_DATA
            or order_status == DecisionPolicyStatus.MISSING_REQUIRED_DATA
        )
        liquidity_invalid = (
            (
                liquidity_value is not _MISSING
                and liquidity_value is not None
                and not isinstance(liquidity_value, bool)
            )
            or adv20_status == DecisionPolicyStatus.VALIDATION_FAILED
            or order_status == DecisionPolicyStatus.VALIDATION_FAILED
            or (adv20 is not None and adv20 <= 0)
            or (order_notional is not None and order_notional <= 0)
        )
        capacity = adv20 * self.config.maximum_adv_participation if adv20 is not None else None
        liquidity_actual = (
            "MISSING"
            if liquidity_missing
            else {"adv20_ntd": adv20, "order_notional": order_notional}
        )
        if liquidity_missing:
            liquidity_gate = _gate(
                "liquidity_capacity_gate",
                False,
                liquidity_actual,
                {"maximum_order_notional": capacity},
                "LIQUIDITY_INPUT_MISSING",
                policy_status=DecisionPolicyStatus.MISSING_REQUIRED_DATA,
            )
        elif liquidity_invalid:
            liquidity_gate = _gate(
                "liquidity_capacity_gate",
                False,
                liquidity_actual,
                {"maximum_order_notional": capacity},
                "LIQUIDITY_INPUT_INVALID",
                policy_status=DecisionPolicyStatus.VALIDATION_FAILED,
            )
        else:
            assert isinstance(liquidity_value, bool)
            assert order_notional is not None and capacity is not None
            liquidity_gate = _gate(
                "liquidity_capacity_gate",
                liquidity_value and order_notional <= capacity,
                liquidity_actual,
                {"maximum_order_notional": capacity},
                "LIQUIDITY_OR_CAPACITY_FAIL",
            )

        exposure_value = _raw_value(row, "market_exposure_cap")
        exposure, exposure_status = _number(exposure_value)
        if exposure_status == DecisionPolicyStatus.MISSING_REQUIRED_DATA:
            market_gate = _gate(
                "market_exposure_cap",
                False,
                "MISSING",
                "> 0",
                "MARKET_EXPOSURE_INPUT_MISSING",
                policy_status=DecisionPolicyStatus.MISSING_REQUIRED_DATA,
            )
        elif (
            exposure_status == DecisionPolicyStatus.VALIDATION_FAILED
            or exposure is None
            or not 0 <= exposure <= 1
        ):
            market_gate = _gate(
                "market_exposure_cap",
                False,
                exposure_value,
                "> 0",
                "MARKET_EXPOSURE_INPUT_INVALID",
                policy_status=DecisionPolicyStatus.VALIDATION_FAILED,
            )
        else:
            market_gate = _gate(
                "market_exposure_cap",
                exposure > 0,
                exposure,
                "> 0",
                "MARKET_EXPOSURE_ZERO",
            )

        probability_values = (
            _raw_value(row, "calibrated_p_up"),
            _raw_value(row, "calibrated_p_neutral"),
            _raw_value(row, "calibrated_p_down"),
        )
        parsed_probabilities = tuple(_number(value) for value in probability_values)
        p_up, p_neutral, p_down = (
            parsed_probabilities[0][0],
            parsed_probabilities[1][0],
            parsed_probabilities[2][0],
        )
        calibration_version = _raw_value(row, "calibration_version")
        direction_missing = (
            any(
                status == DecisionPolicyStatus.MISSING_REQUIRED_DATA
                for _, status in parsed_probabilities
            )
            or calibration_version is _MISSING
            or calibration_version is None
            or not has_valid_calibration_version(calibration_version)
        )
        direction_invalid = any(
            status == DecisionPolicyStatus.VALIDATION_FAILED for _, status in parsed_probabilities
        ) or (not direction_missing and not _valid_probability_vector((p_up, p_neutral, p_down)))
        if direction_missing:
            direction_fail_code = "DIRECTION_CALIBRATION_MISSING"
            direction_status = DecisionPolicyStatus.MISSING_REQUIRED_DATA
        elif direction_invalid:
            direction_fail_code = "INVALID_CALIBRATED_PROBABILITIES"
            direction_status = DecisionPolicyStatus.VALIDATION_FAILED
        else:
            direction_fail_code = "DIRECTION_THRESHOLD_FAIL"
            direction_status = DecisionPolicyStatus.EVALUATED
        direction_pass = bool(
            direction_status == DecisionPolicyStatus.EVALUATED
            and p_up is not None
            and p_down is not None
            and p_up >= self.config.minimum_p_up
            and p_up - p_down >= self.config.minimum_probability_spread
        )
        direction_gate = _gate(
            "calibrated_direction_probabilities",
            direction_pass,
            {
                "p_up": p_up,
                "p_neutral": p_neutral,
                "p_down": p_down,
                "calibration_version": calibration_version,
            },
            {
                "minimum_p_up": self.config.minimum_p_up,
                "minimum_p_up_minus_p_down": self.config.minimum_probability_spread,
                "sum": 1.0,
                "calibration_version": "required",
            },
            direction_fail_code,
            policy_status=direction_status,
        )

        quantile_values = (
            _raw_value(row, "net_q10"),
            _raw_value(row, "net_q50"),
            _raw_value(row, "net_q90"),
        )
        parsed_quantiles = tuple(_number(value) for value in quantile_values)
        q10, q50, q90 = (
            parsed_quantiles[0][0],
            parsed_quantiles[1][0],
            parsed_quantiles[2][0],
        )
        calibration_status = _raw_value(row, "calibration_status")
        quantile_missing = (
            any(
                status == DecisionPolicyStatus.MISSING_REQUIRED_DATA
                for _, status in parsed_quantiles
            )
            or calibration_status is _MISSING
            or calibration_status is None
            or not has_calibrated_interval_status(calibration_status)
        )
        quantile_invalid = any(
            status == DecisionPolicyStatus.VALIDATION_FAILED for _, status in parsed_quantiles
        ) or (
            not quantile_missing
            and (q10 is None or q50 is None or q90 is None or not q10 <= q50 <= q90)
        )
        if quantile_missing:
            quantile_fail_code = "QUANTILE_NOT_CALIBRATED"
            quantile_status = DecisionPolicyStatus.MISSING_REQUIRED_DATA
        elif quantile_invalid:
            quantile_fail_code = "NON_MONOTONIC_QUANTILES"
            quantile_status = DecisionPolicyStatus.VALIDATION_FAILED
        else:
            quantile_fail_code = "NET_QUANTILE_THRESHOLD_FAIL"
            quantile_status = DecisionPolicyStatus.EVALUATED
        quantile_pass = bool(
            quantile_status == DecisionPolicyStatus.EVALUATED
            and q10 is not None
            and q50 is not None
            and q50 > self.config.minimum_net_q50
            and q10 >= -self.config.maximum_net_q10_loss
        )
        quantile_gate = _gate(
            "net_quantile_thresholds",
            quantile_pass,
            {
                "net_q10": q10,
                "net_q50": q50,
                "net_q90": q90,
                "calibration_status": calibration_status,
            },
            {
                "minimum_net_q50": self.config.minimum_net_q50,
                "minimum_net_q10": -self.config.maximum_net_q10_loss,
                "monotonic": True,
                "calibration_status": "CALIBRATED:<version>",
            },
            quantile_fail_code,
            policy_status=quantile_status,
        )

        rank_score_value = _raw_value(row, "rank_score")
        global_rank_value = _raw_value(row, "global_rank")
        rank_score, rank_score_status = _number(rank_score_value)
        global_rank_number, global_rank_status = _number(global_rank_value)
        rank_missing = (
            rank_score_status == DecisionPolicyStatus.MISSING_REQUIRED_DATA
            or global_rank_status == DecisionPolicyStatus.MISSING_REQUIRED_DATA
        )
        rank_invalid = (
            rank_score_status == DecisionPolicyStatus.VALIDATION_FAILED
            or global_rank_status == DecisionPolicyStatus.VALIDATION_FAILED
            or (rank_score is not None and not 0 <= rank_score <= 100)
            or (
                global_rank_number is not None
                and (global_rank_number <= 0 or not global_rank_number.is_integer())
            )
        )
        global_rank = (
            int(global_rank_number)
            if global_rank_number is not None and global_rank_number.is_integer()
            else None
        )
        if rank_missing:
            rank_gate = _gate(
                "rank_eligibility",
                False,
                "MISSING",
                "present",
                "RANK_UNAVAILABLE",
                policy_status=DecisionPolicyStatus.MISSING_REQUIRED_DATA,
            )
        elif rank_invalid:
            rank_gate = _gate(
                "rank_eligibility",
                False,
                {"rank_score": rank_score_value, "global_rank": global_rank_value},
                "valid rank",
                "RANK_INVALID",
                policy_status=DecisionPolicyStatus.VALIDATION_FAILED,
            )
        else:
            rank_gate = _gate(
                "rank_eligibility",
                True,
                {"rank_score": rank_score, "global_rank": global_rank},
                "present",
                "RANK_UNAVAILABLE",
            )

        position_limit_value = _raw_value(row, "position_limits_pass")
        if position_limit_value is _MISSING or position_limit_value is None:
            position_gate = _gate(
                "position_capacity_limits",
                False,
                "MISSING",
                True,
                "POSITION_LIMIT_INPUT_MISSING",
                policy_status=DecisionPolicyStatus.MISSING_REQUIRED_DATA,
            )
        elif not isinstance(position_limit_value, bool):
            position_gate = _gate(
                "position_capacity_limits",
                False,
                position_limit_value,
                True,
                "POSITION_LIMIT_INPUT_INVALID",
                policy_status=DecisionPolicyStatus.VALIDATION_FAILED,
            )
        else:
            position_gate = _gate(
                "position_capacity_limits",
                position_limit_value,
                position_limit_value,
                True,
                "POSITION_LIMIT_FAIL",
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
        decision_policy_status = _highest_status(gates)
        if decision_policy_status != DecisionPolicyStatus.EVALUATED:
            decision = None
        elif any(not gate.passed for gate in gates[:6]) or not position_gate.passed:
            decision = Decision.NO_TRADE
        else:
            decision = Decision.CANDIDATE
        return DecisionResult(
            symbol=str(row["symbol"]),
            horizon=horizon,
            decision=decision,
            decision_policy_status=decision_policy_status,
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
                (
                    result
                    for result in date_results
                    if result.decision_policy_status == DecisionPolicyStatus.EVALUATED
                    and result.decision == Decision.CANDIDATE
                ),
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
