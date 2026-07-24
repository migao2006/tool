"""Validate and resolve auditable RESEARCH_ONLY decision-gate payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import cast

from src.decision.decision_policy import DECISION_GATE_ORDER


GATE_ENVELOPE_VERSION = "research-decision-gate.v1"


def parse_prediction_gates(
    prediction: Mapping[str, object],
    *,
    snapshot_date: date,
) -> tuple[Mapping[str, object], ...]:
    """Return a complete gate set, or an empty tuple for a legacy artifact."""

    raw = prediction.get("gates")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("research decision gates must contain all eight gates")
    raw_gates = cast(list[object], raw)
    if len(raw_gates) != len(DECISION_GATE_ORDER):
        raise ValueError("research decision gates must contain all eight gates")
    gates = tuple(
        cast(Mapping[str, object], value) for value in raw_gates if isinstance(value, Mapping)
    )
    if len(gates) != len(raw_gates):
        raise ValueError("research decision gates must be JSON objects")
    if tuple(str(gate.get("gate", "")) for gate in gates) != DECISION_GATE_ORDER:
        raise ValueError("research decision gates are missing or out of order")
    for gate in gates:
        if not isinstance(gate.get("passed"), bool):
            raise ValueError("research decision gate passed must be boolean")
        if "actual" not in gate or gate.get("actual") is None:
            raise ValueError("research decision gate actual is required")
        if "threshold" not in gate or gate.get("threshold") is None:
            raise ValueError("research decision gate threshold is required")
        reason_code = gate.get("reason_code")
        if not isinstance(reason_code, str) or not reason_code.strip():
            raise ValueError("research decision gate reason_code is required")
        source_date = gate.get("source_date")
        if source_date is None:
            continue
        if not isinstance(source_date, str):
            raise ValueError("research decision gate source_date must be a date")
        try:
            parsed = date.fromisoformat(source_date)
        except ValueError as error:
            raise ValueError("research decision gate source_date must use YYYY-MM-DD") from error
        if parsed.isoformat() != source_date or parsed > snapshot_date:
            raise ValueError("research decision gate source_date is invalid")
    return gates


def resolve_gate_rows(
    predictions: Sequence[Mapping[str, object]],
    security_ids: Mapping[str, int],
    *,
    snapshot_sha256: str,
    snapshot_date: date,
) -> tuple[Mapping[str, object], ...]:
    """Resolve validated symbol gates to database security identifiers."""

    resolved: list[Mapping[str, object]] = []
    gated_count = 0
    for prediction in predictions:
        gates = parse_prediction_gates(prediction, snapshot_date=snapshot_date)
        if not gates:
            continue
        gated_count += 1
        symbol = str(prediction["symbol"])
        for order, gate in enumerate(gates, start=1):
            resolved.append(
                {
                    "security_id": security_ids[symbol],
                    "gate_order": order,
                    "gate_name": gate["gate"],
                    "passed": gate["passed"],
                    "actual_value": {
                        "contract_version": GATE_ENVELOPE_VERSION,
                        "value": gate["actual"],
                        "source_date": gate.get("source_date"),
                        "attachment_snapshot_sha256": snapshot_sha256,
                    },
                    "threshold_value": gate["threshold"],
                    "reason_code": gate["reason_code"],
                }
            )
    if gated_count not in {0, len(predictions)}:
        raise ValueError("one research snapshot cannot mix gated and legacy rows")
    return tuple(resolved)


__all__ = [
    "GATE_ENVELOPE_VERSION",
    "parse_prediction_gates",
    "resolve_gate_rows",
]
