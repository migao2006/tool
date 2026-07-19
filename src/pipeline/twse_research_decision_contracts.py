"""Typed outputs for research-only decision-policy evaluation."""

from __future__ import annotations

# pyright: reportAny=false, reportExplicitAny=false, reportUnknownVariableType=false

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from src.decision.decision_policy import DECISION_GATE_ORDER, Decision


@dataclass(frozen=True)
class ResearchDecisionPolicyInputs:
    """Formal inputs absent from the price-only research prediction row."""

    data_quality_hard_fail: bool | None = None
    tradable: bool | None = None
    liquidity_pass: bool | None = None
    estimated_order_notional_ntd: float | None = None
    market_exposure_cap: float | None = None
    position_limits_pass: bool | None = None
    gate_source_dates: Mapping[str, date | str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class ResearchDecisionGate:
    gate: str
    passed: bool
    actual: Any
    threshold: Any
    reason_code: str
    source_date: str | None

    def __post_init__(self) -> None:
        if self.source_date is None:
            return
        try:
            parsed = date.fromisoformat(self.source_date)
        except ValueError as error:
            raise ValueError("gate source_date must use YYYY-MM-DD") from error
        if parsed.isoformat() != self.source_date:
            raise ValueError("gate source_date must use YYYY-MM-DD")

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "passed": self.passed,
            "actual": self.actual,
            "threshold": self.threshold,
            "reason_code": self.reason_code,
            "source_date": self.source_date,
        }


@dataclass(frozen=True)
class ResearchDecisionPolicyResult:
    symbol: str
    horizon: int
    decision: Decision
    rank_score: float | None
    global_rank: int | None
    gates: tuple[ResearchDecisionGate, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.horizon != 5:
            raise ValueError("UNSUPPORTED_HORIZON")
        if self.decision == Decision.CANDIDATE:
            raise ValueError("research decision policy cannot emit CANDIDATE")
        if tuple(gate.gate for gate in self.gates) != DECISION_GATE_ORDER:
            raise ValueError("research decision gates must follow the complete order")

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "horizon": self.horizon,
            "decision": self.decision.value,
            "rank_score": self.rank_score,
            "global_rank": self.global_rank,
            "gates": [gate.to_dict() for gate in self.gates],
            "reason_codes": list(self.reason_codes),
        }


__all__ = [
    "ResearchDecisionGate",
    "ResearchDecisionPolicyInputs",
    "ResearchDecisionPolicyResult",
]
