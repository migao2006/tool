from __future__ import annotations

from src.decision.decision_policy import (
    Decision,
    DecisionPolicy,
    DecisionPolicyConfig,
    DecisionPolicyStatus,
)
from src.decision.position_sizing import PositionLimits, allocate_inverse_volatility


def valid_row(symbol: str = "2330", rank: int = 1) -> dict[str, object]:
    return {
        "symbol": symbol,
        "horizon": 5,
        "data_quality_status": "PASS",
        "data_quality_hard_fail": False,
        "tradable": True,
        "liquidity_pass": True,
        "adv20": 20_000_000.0,
        "estimated_order_notional_ntd": 100_000.0,
        "market_exposure_cap": 0.6,
        "calibrated_p_up": 0.65,
        "calibrated_p_neutral": 0.25,
        "calibrated_p_down": 0.10,
        "calibration_version": "direction-cal-v1",
        "net_q10": -0.03,
        "net_q50": 0.02,
        "net_q90": 0.08,
        "calibration_status": "CALIBRATED:interval-cal-v1",
        "rank_score": 99.0 - rank,
        "global_rank": rank,
        "position_limits_pass": True,
    }


def test_policy_exposes_all_eight_gates_in_required_order() -> None:
    result = DecisionPolicy().evaluate(valid_row())
    assert result.decision == Decision.CANDIDATE
    assert result.decision_policy_status == DecisionPolicyStatus.EVALUATED
    assert [gate.gate for gate in result.gates] == [
        "data_quality_hard_gate",
        "tradability_gate",
        "liquidity_capacity_gate",
        "market_exposure_cap",
        "calibrated_direction_probabilities",
        "net_quantile_thresholds",
        "rank_eligibility",
        "position_capacity_limits",
    ]


def test_high_rank_with_bad_probability_is_no_trade_not_reweighted() -> None:
    row = valid_row(rank=1)
    row["calibrated_p_up"] = 0.30
    row["calibrated_p_neutral"] = 0.50
    row["calibrated_p_down"] = 0.20
    result = DecisionPolicy().evaluate(row)
    assert result.decision == Decision.NO_TRADE
    assert result.decision_policy_status == DecisionPolicyStatus.EVALUATED
    assert "DIRECTION_THRESHOLD_FAIL" in result.reason_codes


def test_missing_calibration_evidence_is_not_a_no_trade_decision() -> None:
    row = valid_row()
    row["calibration_version"] = "not-trained"
    row["calibration_status"] = "UNCALIBRATED"

    result = DecisionPolicy().evaluate(row)

    assert result.decision is None
    assert result.decision_policy_status == DecisionPolicyStatus.MISSING_REQUIRED_DATA
    assert "DIRECTION_CALIBRATION_MISSING" in result.reason_codes
    assert "QUANTILE_NOT_CALIBRATED" in result.reason_codes


def test_hard_quality_fail_can_never_be_candidate() -> None:
    row = valid_row()
    row["data_quality_status"] = "FAIL"
    row["reason_codes"] = ("DISPOSITION_SECURITY",)
    result = DecisionPolicy().evaluate(row)
    assert result.decision is None
    assert result.decision_policy_status == DecisionPolicyStatus.HARD_FAIL
    assert "DISPOSITION_SECURITY" in result.reason_codes


def test_missing_market_policy_input_is_not_a_no_trade_decision() -> None:
    row = valid_row()
    row["market_exposure_cap"] = None

    result = DecisionPolicy().evaluate(row)

    assert result.decision is None
    assert result.decision_policy_status == DecisionPolicyStatus.MISSING_REQUIRED_DATA
    assert "MARKET_EXPOSURE_INPUT_MISSING" in result.reason_codes


def test_invalid_probability_vector_is_a_validation_failure() -> None:
    row = valid_row()
    row["calibrated_p_up"] = 0.90

    result = DecisionPolicy().evaluate(row)

    assert result.decision is None
    assert result.decision_policy_status == DecisionPolicyStatus.VALIDATION_FAILED
    assert "INVALID_CALIBRATED_PROBABILITIES" in result.reason_codes


def test_known_non_tradable_security_is_an_evaluated_no_trade() -> None:
    row = valid_row()
    row["tradable"] = False

    result = DecisionPolicy().evaluate(row)

    assert result.decision == Decision.NO_TRADE
    assert result.decision_policy_status == DecisionPolicyStatus.EVALUATED
    assert "NOT_TRADABLE" in result.reason_codes


def test_top_k_uses_global_rank_only() -> None:
    policy = DecisionPolicy(DecisionPolicyConfig(top_k=1))
    first = valid_row("A", rank=2)
    second = valid_row("B", rank=1)
    first["calibrated_p_up"] = 0.90
    first["calibrated_p_neutral"] = 0.05
    first["calibrated_p_down"] = 0.05
    results = policy.select_top_k([first, second])
    by_symbol = {result.symbol: result for result in results}
    assert by_symbol["B"].decision == Decision.CANDIDATE
    assert by_symbol["A"].decision == Decision.WATCH


def test_top_k_is_applied_independently_per_decision_date() -> None:
    policy = DecisionPolicy(DecisionPolicyConfig(top_k=1))
    rows = []
    for decision_date, prefix in (("2026-01-02", "A"), ("2026-01-05", "B")):
        first = valid_row(f"{prefix}1", rank=1)
        second = valid_row(f"{prefix}2", rank=2)
        first["decision_date"] = decision_date
        second["decision_date"] = decision_date
        rows.extend((first, second))
    results = policy.select_top_k(rows)
    assert sum(result.decision == Decision.CANDIDATE for result in results) == 2


def test_position_sizing_respects_single_name_industry_and_adv_limits() -> None:
    weights = allocate_inverse_volatility(
        [
            {"symbol": "A", "industry": "X", "forecast_volatility": 0.2, "adv20": 10_000_000},
            {"symbol": "B", "industry": "X", "forecast_volatility": 0.1, "adv20": 10_000_000},
        ],
        portfolio_equity=1_000_000,
        market_exposure_cap=0.8,
        limits=PositionLimits(0.1, 0.15, 0.01),
    )
    assert max(weights.values()) <= 0.1
    assert sum(weights.values()) <= 0.15
