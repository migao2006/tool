from __future__ import annotations

# pyright: reportAny=false, reportMissingImports=false, reportUnknownMemberType=false

from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.config.loader import load_mvp_config
from src.decision.decision_policy import (
    DECISION_GATE_ORDER,
    Decision,
    DecisionPolicyStatus,
)
from src.pipeline.research_decision_policy_evidence import (
    RequiredEvidenceCategory,
    RequiredPolicyEvidence,
)
from src.pipeline.twse_research_decision_policy_adapter import (
    ResearchDecisionPolicyInputs,
    TwseResearchDecisionPolicyAdapter,
)
from src.pipeline.twse_research_prediction_contracts import (
    TwseOosResearchPrediction,
)


AS_OF_DATE = date(2026, 7, 17)


def _prediction() -> TwseOosResearchPrediction:
    return TwseOosResearchPrediction(
        symbol="2330",
        decision_date=AS_OF_DATE,
        decision_at=datetime(2026, 7, 17, 17, tzinfo=ZoneInfo("Asia/Taipei")),
        horizon=5,
        fold_number=4,
        model_raw_score=0.9,
        rank_score=99.0,
        global_rank=1,
        global_rank_percentile=0.99,
        calibrated_p_up=0.65,
        calibrated_p_neutral=0.25,
        calibrated_p_down=0.10,
        calibration_version="direction-cal-v1",
        gross_q10=-0.02,
        gross_q50=0.03,
        gross_q90=0.08,
        net_q10=-0.03,
        net_q50=0.02,
        net_q90=0.07,
        interval_width=0.10,
        calibration_status="CALIBRATED:interval-cal-v1",
        quantile_crossing_before_calibration=False,
        estimated_round_trip_cost=0.01,
        latest_available_at=datetime(
            2026,
            7,
            17,
            16,
            tzinfo=ZoneInfo("Asia/Taipei"),
        ),
        data_quality_status="PASS",
        reason_codes=("POINT_IN_TIME_UNVERIFIED",),
        adv20_ntd=20_000_000.0,
        maximum_order_notional_ntd=200_000.0,
        evaluation_scope="RETROSPECTIVE_RESEARCH_INFERENCE",
    )


def _complete_inputs() -> ResearchDecisionPolicyInputs:
    available_at = datetime(
        2026,
        7,
        17,
        16,
        tzinfo=ZoneInfo("Asia/Taipei"),
    )
    tradability = RequiredPolicyEvidence.available(
        category=RequiredEvidenceCategory.TRADABILITY,
        value=True,
        source="TWSE_MOPS_SNAPSHOT",
        market="TWSE",
        symbol="2330",
        effective_date=AS_OF_DATE,
        available_at=available_at,
        publication_id="security-state-2330",
        details={
            "trading_status": "ACTIVE",
            "attention_flag": False,
            "disposal_flag": False,
            "altered_trading_method_flag": False,
            "full_cash_delivery_flag": False,
            "periodic_auction_flag": False,
            "suspended_flag": False,
        },
    )
    market = RequiredPolicyEvidence.available(
        category=RequiredEvidenceCategory.MARKET_EXPOSURE,
        value=0.6,
        source="TWSE_MARKET_MODEL",
        market="TWSE",
        symbol=None,
        effective_date=AS_OF_DATE,
        available_at=available_at,
        publication_id="market-run-17",
        details={
            "calibrated_p_up": 0.55,
            "calibrated_p_neutral": 0.30,
            "calibrated_p_down": 0.15,
            "market_regime": "UPTREND_LOW_VOL_BROAD",
            "forecast_market_volatility": 0.012,
            "model_version": "twse-market-h5-v1",
            "training_end_date": "2026-07-16",
        },
    )
    position = RequiredPolicyEvidence.available(
        category=RequiredEvidenceCategory.POSITION_LIMITS,
        value=True,
        source="PORTFOLIO_POLICY_ENGINE",
        market="TWSE",
        symbol="2330",
        effective_date=AS_OF_DATE,
        available_at=available_at,
        publication_id="portfolio-state-2330",
        details={
            "portfolio_policy_version": "portfolio-h5-v1",
            "portfolio_state_id": "portfolio-20260717-1600",
            "maximum_single_name_weight": 0.10,
            "maximum_industry_weight": 0.25,
            "maximum_adv_participation": 0.01,
            "proposed_weight": 0.04,
            "resulting_industry_weight": 0.18,
            "proposed_adv_participation": 0.005,
        },
    )
    return ResearchDecisionPolicyInputs(
        data_quality_hard_fail=False,
        tradable=True,
        liquidity_pass=True,
        estimated_order_notional_ntd=100_000.0,
        market_exposure_cap=0.6,
        position_limits_pass=True,
        gate_source_dates={gate: AS_OF_DATE for gate in DECISION_GATE_ORDER},
        required_evidence={
            item.gate: item for item in (tradability, market, position)
        },
    )


def test_complete_authoritative_evidence_produces_an_evaluated_candidate() -> None:
    result = TwseResearchDecisionPolicyAdapter(load_mvp_config()).evaluate(
        _prediction(),
        _complete_inputs(),
    )

    assert result.decision == Decision.CANDIDATE
    assert result.decision_policy_status == DecisionPolicyStatus.EVALUATED
    assert [gate.gate for gate in result.gates] == list(DECISION_GATE_ORDER)
    assert all(gate.passed for gate in result.gates)
    assert {gate.source_date for gate in result.gates} == {"2026-07-17"}
    assert "RESEARCH_ONLY_DECISION_POLICY_NO_CANDIDATE" not in result.reason_codes
    assert result.to_dict()["decision"] == "CANDIDATE"
    assert result.to_dict()["decision_policy_status"] == "EVALUATED"
    assert all("source_date" in gate for gate in result.to_dict()["gates"])


def test_missing_formal_inputs_fail_closed_without_inventing_source_dates() -> None:
    result = TwseResearchDecisionPolicyAdapter(load_mvp_config()).evaluate(_prediction())
    by_name = {gate.gate: gate for gate in result.gates}

    assert result.decision is None
    assert result.decision_policy_status == DecisionPolicyStatus.MISSING_REQUIRED_DATA
    assert by_name["data_quality_hard_gate"].reason_code == (
        "FORMAL_DATA_QUALITY_HARD_FAIL_INPUT_MISSING"
    )
    assert by_name["tradability_gate"].reason_code == ("FORMAL_TRADABILITY_INPUT_MISSING")
    assert by_name["liquidity_capacity_gate"].reason_code == ("FORMAL_LIQUIDITY_INPUT_MISSING")
    assert by_name["market_exposure_cap"].reason_code == ("FORMAL_MARKET_EXPOSURE_INPUT_MISSING")
    assert by_name["position_capacity_limits"].reason_code == (
        "FORMAL_POSITION_LIMIT_INPUT_MISSING"
    )
    for gate_name in (
        "data_quality_hard_gate",
        "tradability_gate",
        "liquidity_capacity_gate",
        "market_exposure_cap",
        "position_capacity_limits",
    ):
        assert by_name[gate_name].source_date is None
        assert not by_name[gate_name].passed
        assert by_name[gate_name].actual == "MISSING"
    for gate_name in (
        "calibrated_direction_probabilities",
        "net_quantile_thresholds",
        "rank_eligibility",
    ):
        assert by_name[gate_name].source_date == "2026-07-17"
    assert "NOT_TRADABLE" not in result.reason_codes
    assert "LIQUIDITY_OR_CAPACITY_FAIL" not in result.reason_codes
    assert "MARKET_EXPOSURE_ZERO" not in result.reason_codes
    assert "POSITION_LIMIT_FAIL" not in result.reason_codes
    assert result.to_dict()["decision"] is None
    assert result.to_dict()["decision_policy_status"] == "MISSING_REQUIRED_DATA"


def test_warn_quality_is_not_misreported_as_a_known_hard_fail() -> None:
    result = TwseResearchDecisionPolicyAdapter(load_mvp_config()).evaluate(
        replace(_prediction(), data_quality_status="WARN"),
        _complete_inputs(),
    )
    gate = next(value for value in result.gates if value.gate == "data_quality_hard_gate")

    assert not gate.passed
    assert gate.actual == "WARN"
    assert gate.reason_code == "DATA_QUALITY_NOT_FORMALLY_VERIFIED"
    assert "DATA_QUALITY_HARD_FAIL" not in result.reason_codes
    assert result.decision is None
    assert result.decision_policy_status == DecisionPolicyStatus.VALIDATION_FAILED


def test_gate_with_future_source_date_is_failed_closed() -> None:
    inputs = _complete_inputs()
    source_dates = dict(inputs.gate_source_dates)
    source_dates["liquidity_capacity_gate"] = date(2026, 7, 18)

    result = TwseResearchDecisionPolicyAdapter(load_mvp_config()).evaluate(
        _prediction(),
        replace(inputs, gate_source_dates=source_dates),
    )
    gate = next(
        value for value in result.gates if value.gate == "liquidity_capacity_gate"
    )

    assert not gate.passed
    assert gate.source_date == "2026-07-18"
    assert gate.reason_code == "DECISION_GATE_SOURCE_DATE_AFTER_DECISION"
    assert result.decision is None
    assert result.decision_policy_status == DecisionPolicyStatus.VALIDATION_FAILED


def test_complete_policy_rejection_remains_an_evaluated_no_trade() -> None:
    result = TwseResearchDecisionPolicyAdapter(load_mvp_config()).evaluate(
        replace(_prediction(), net_q10=-0.08, interval_width=0.15),
        _complete_inputs(),
    )

    assert result.decision == Decision.NO_TRADE
    assert result.decision_policy_status == DecisionPolicyStatus.EVALUATED
    assert "NET_QUANTILE_THRESHOLD_FAIL" in result.reason_codes


def test_non_five_day_prediction_is_rejected() -> None:
    with pytest.raises(ValueError, match="^UNSUPPORTED_HORIZON$"):
        _ = TwseResearchDecisionPolicyAdapter(replace(load_mvp_config(), horizon=2))
