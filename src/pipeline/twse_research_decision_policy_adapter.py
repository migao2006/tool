"""Fail-closed DecisionPolicy adapter for TWSE research predictions."""

from __future__ import annotations

# pyright: reportAny=false, reportExplicitAny=false, reportUnknownVariableType=false

from datetime import date, datetime
from typing import final

from src.config.types import MvpConfig
from src.decision.decision_policy import (
    Decision,
    DecisionPolicy,
    DecisionPolicyConfig,
    DecisionPolicyStatus,
    DecisionResult,
    GateResult,
)

from .twse_research_decision_contracts import (
    ResearchDecisionGate,
    ResearchDecisionPolicyInputs,
    ResearchDecisionPolicyResult,
)
from .twse_research_prediction_contracts import TwseOosResearchPrediction


RESEARCH_ONLY_POLICY_REASON = "RESEARCH_ONLY_DECISION_POLICY_NO_CANDIDATE"

_DEFAULT_RESEARCH_SOURCE_GATES = frozenset(
    {
        "calibrated_direction_probabilities",
        "net_quantile_thresholds",
        "rank_eligibility",
    }
)
_STATUS_PRIORITY = {
    DecisionPolicyStatus.EVALUATED: 0,
    DecisionPolicyStatus.VALIDATION_FAILED: 1,
    DecisionPolicyStatus.MISSING_REQUIRED_DATA: 2,
    DecisionPolicyStatus.HARD_FAIL: 3,
}


def _merge_status(
    left: DecisionPolicyStatus,
    right: DecisionPolicyStatus,
) -> DecisionPolicyStatus:
    return max((left, right), key=_STATUS_PRIORITY.__getitem__)


def _policy_config(config: MvpConfig) -> DecisionPolicyConfig:
    if config.horizon != 5:
        raise ValueError("UNSUPPORTED_HORIZON")
    return DecisionPolicyConfig(
        horizon=5,
        minimum_p_up=config.decision.minimum_p_up,
        minimum_probability_spread=config.decision.minimum_probability_spread,
        minimum_net_q50=config.decision.minimum_net_q50,
        maximum_net_q10_loss=config.decision.maximum_net_q10_loss,
        top_k=config.decision.top_k,
        maximum_adv_participation=config.cost.max_adv_participation,
    )


def _source_date(
    value: date | str | None,
    decision_date: date,
) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, datetime):
        return None, "DECISION_GATE_SOURCE_DATE_INVALID"
    try:
        parsed = value if isinstance(value, date) else date.fromisoformat(value)
    except (TypeError, ValueError):
        return None, "DECISION_GATE_SOURCE_DATE_INVALID"
    if parsed > decision_date:
        return parsed.isoformat(), "DECISION_GATE_SOURCE_DATE_AFTER_DECISION"
    return parsed.isoformat(), None


def _missing_input_reason(
    gate: str,
    inputs: ResearchDecisionPolicyInputs,
) -> str | None:
    required = {
        "data_quality_hard_gate": (
            inputs.data_quality_hard_fail,
            "FORMAL_DATA_QUALITY_HARD_FAIL_INPUT_MISSING",
        ),
        "tradability_gate": (
            inputs.tradable,
            "FORMAL_TRADABILITY_INPUT_MISSING",
        ),
        "liquidity_capacity_gate": (
            inputs.liquidity_pass,
            "FORMAL_LIQUIDITY_INPUT_MISSING",
        ),
        "market_exposure_cap": (
            inputs.market_exposure_cap,
            "FORMAL_MARKET_EXPOSURE_INPUT_MISSING",
        ),
        "position_capacity_limits": (
            inputs.position_limits_pass,
            "FORMAL_POSITION_LIMIT_INPUT_MISSING",
        ),
    }
    value_and_reason = required.get(gate)
    if value_and_reason is None or value_and_reason[0] is not None:
        return None
    return value_and_reason[1]


@final
class TwseResearchDecisionPolicyAdapter:
    """Run the existing policy while preserving the RESEARCH_ONLY boundary."""

    def __init__(self, config: MvpConfig) -> None:
        self._config = config
        self._policy = DecisionPolicy(_policy_config(config))

    def evaluate(
        self,
        prediction: TwseOosResearchPrediction,
        inputs: ResearchDecisionPolicyInputs | None = None,
    ) -> ResearchDecisionPolicyResult:
        if prediction.horizon != 5:
            raise ValueError("UNSUPPORTED_HORIZON")
        resolved_inputs = inputs or ResearchDecisionPolicyInputs()
        policy_result = self._policy.evaluate(self._policy_row(prediction, resolved_inputs))
        gates, adapter_reasons, decision_policy_status = self._adapt_gates(
            prediction,
            resolved_inputs,
            policy_result,
        )
        decision = (
            policy_result.decision
            if decision_policy_status == DecisionPolicyStatus.EVALUATED
            else None
        )
        boundary_reasons: tuple[str, ...] = ()
        if decision == Decision.CANDIDATE:
            decision = None
            decision_policy_status = DecisionPolicyStatus.VALIDATION_FAILED
            boundary_reasons = (RESEARCH_ONLY_POLICY_REASON,)
        reason_codes = tuple(
            dict.fromkeys(
                (
                    *prediction.reason_codes,
                    *adapter_reasons,
                    *boundary_reasons,
                )
            )
        )
        return ResearchDecisionPolicyResult(
            symbol=policy_result.symbol,
            horizon=policy_result.horizon,
            decision=decision,
            decision_policy_status=decision_policy_status,
            rank_score=policy_result.rank_score,
            global_rank=policy_result.global_rank,
            gates=gates,
            reason_codes=reason_codes,
        )

    def _policy_row(
        self,
        prediction: TwseOosResearchPrediction,
        inputs: ResearchDecisionPolicyInputs,
    ) -> dict[str, object]:
        estimated_notional = (
            inputs.estimated_order_notional_ntd
            if inputs.estimated_order_notional_ntd is not None
            else self._config.cost.estimated_order_notional_ntd
        )
        return {
            "symbol": prediction.symbol,
            "horizon": prediction.horizon,
            "decision_date": prediction.decision_date,
            "data_quality_status": prediction.data_quality_status,
            "data_quality_hard_fail": inputs.data_quality_hard_fail,
            "tradable": inputs.tradable,
            "liquidity_pass": inputs.liquidity_pass,
            "adv20_ntd": prediction.adv20_ntd,
            "estimated_order_notional_ntd": estimated_notional,
            "market_exposure_cap": inputs.market_exposure_cap,
            "calibrated_p_up": prediction.calibrated_p_up,
            "calibrated_p_neutral": prediction.calibrated_p_neutral,
            "calibrated_p_down": prediction.calibrated_p_down,
            "calibration_version": prediction.calibration_version,
            "net_q10": prediction.net_q10,
            "net_q50": prediction.net_q50,
            "net_q90": prediction.net_q90,
            "calibration_status": prediction.calibration_status,
            "rank_score": prediction.rank_score,
            "global_rank": prediction.global_rank,
            "position_limits_pass": inputs.position_limits_pass,
            "reason_codes": prediction.reason_codes,
        }

    @staticmethod
    def _adapt_gates(
        prediction: TwseOosResearchPrediction,
        inputs: ResearchDecisionPolicyInputs,
        policy_result: DecisionResult,
    ) -> tuple[
        tuple[ResearchDecisionGate, ...],
        tuple[str, ...],
        DecisionPolicyStatus,
    ]:
        gates: list[ResearchDecisionGate] = []
        reasons: list[str] = []
        decision_policy_status = policy_result.decision_policy_status
        for gate in policy_result.gates:
            raw_source_date = inputs.gate_source_dates.get(gate.gate)
            if (
                gate.gate not in inputs.gate_source_dates
                and gate.gate in _DEFAULT_RESEARCH_SOURCE_GATES
            ):
                raw_source_date = prediction.decision_date
            source_date, source_reason = _source_date(
                raw_source_date,
                prediction.decision_date,
            )
            missing_reason = _missing_input_reason(gate.gate, inputs)
            if source_date is None and source_reason is None:
                source_reason = "DECISION_GATE_SOURCE_DATE_MISSING"
            if missing_reason is not None or (source_reason == "DECISION_GATE_SOURCE_DATE_MISSING"):
                decision_policy_status = _merge_status(
                    decision_policy_status,
                    DecisionPolicyStatus.MISSING_REQUIRED_DATA,
                )
            elif source_reason is not None:
                decision_policy_status = _merge_status(
                    decision_policy_status,
                    DecisionPolicyStatus.VALIDATION_FAILED,
                )
            passed = gate.passed and missing_reason is None and source_reason is None
            policy_reason = (
                "DATA_QUALITY_NOT_FORMALLY_VERIFIED"
                if gate.gate == "data_quality_hard_gate"
                and prediction.data_quality_status == "WARN"
                and inputs.data_quality_hard_fail is not True
                else gate.reason_code
            )
            reason_code = "PASS" if passed else missing_reason or source_reason or policy_reason
            gates.append(
                _research_gate(
                    gate,
                    passed=passed,
                    actual="MISSING" if missing_reason is not None else gate.actual,
                    reason_code=reason_code,
                    source_date=source_date,
                )
            )
            if missing_reason is not None:
                reasons.append(missing_reason)
            if source_reason is not None:
                reasons.append(source_reason)
            if not gate.passed and missing_reason is None and source_reason is None:
                reasons.append(policy_reason)
        return (
            tuple(gates),
            tuple(dict.fromkeys(reasons)),
            decision_policy_status,
        )


def _research_gate(
    gate: GateResult,
    *,
    passed: bool,
    actual: object,
    reason_code: str,
    source_date: str | None,
) -> ResearchDecisionGate:
    return ResearchDecisionGate(
        gate=gate.gate,
        passed=passed,
        actual=actual,
        threshold=gate.threshold,
        reason_code=reason_code,
        source_date=source_date,
    )


__all__ = [
    "RESEARCH_ONLY_POLICY_REASON",
    "ResearchDecisionGate",
    "ResearchDecisionPolicyInputs",
    "ResearchDecisionPolicyResult",
    "TwseResearchDecisionPolicyAdapter",
]
