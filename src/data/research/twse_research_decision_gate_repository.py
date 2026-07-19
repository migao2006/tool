"""Persist research decision gates with immutable read-back verification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import cast

from .twse_research_prediction_supabase_contracts import SupabaseResearchWriter


_STOCK_COMPARE_FIELDS = (
    "global_rank",
    "rank_score",
    "calibrated_p_up",
    "calibrated_p_neutral",
    "calibrated_p_down",
    "calibration_version",
    "net_q10",
    "net_q50",
    "net_q90",
    "calibration_status",
    "adv20_ntd",
    "maximum_order_notional_ntd",
    "data_quality_status",
    "decision",
)
_NUMERIC_STOCK_FIELDS = frozenset(
    {
        "global_rank",
        "rank_score",
        "calibrated_p_up",
        "calibrated_p_neutral",
        "calibrated_p_down",
        "net_q10",
        "net_q50",
        "net_q90",
        "adv20_ntd",
        "maximum_order_notional_ntd",
    }
)
_GATE_FIELDS = (
    "stock_prediction_id",
    "gate_order",
    "gate_name",
    "passed",
    "actual_value",
    "threshold_value",
    "reason_code",
)


def _same_number(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, ValueError):
        return False


def _stock_rows(
    writer: SupabaseResearchWriter,
    *,
    prediction_run_id: int,
    security_ids: Sequence[int],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    select = "stock_prediction_id,security_id," + ",".join(_STOCK_COMPARE_FIELDS)
    for offset in range(0, len(security_ids), 100):
        batch = security_ids[offset : offset + 100]
        rows.extend(
            writer.select_rows(
                "stock_predictions",
                select=select,
                filters={
                    "prediction_run_id": f"eq.{prediction_run_id}",
                    "security_id": f"in.({','.join(str(value) for value in batch)})",
                },
                limit=len(batch),
            )
        )
    return rows


def _verify_stock_inputs(
    expected: Sequence[Mapping[str, object]],
    actual: Sequence[Mapping[str, object]],
) -> dict[int, int]:
    actual_by_security = {
        int(cast(int | str, row["security_id"])): row for row in actual
    }
    if len(actual_by_security) != len(expected):
        raise ValueError("research gate stock prediction set is incomplete")
    prediction_ids: dict[int, int] = {}
    for row in expected:
        security_id = int(cast(int | str, row["security_id"]))
        stored = actual_by_security.get(security_id)
        if stored is None:
            raise ValueError("research gate stock prediction identity is missing")
        for field_name in _STOCK_COMPARE_FIELDS:
            expected_value = row.get(field_name)
            actual_value = stored.get(field_name)
            matches = (
                _same_number(expected_value, actual_value)
                if field_name in _NUMERIC_STOCK_FIELDS
                else expected_value == actual_value
            )
            if not matches:
                details = f"{security_id}.{field_name}"
                raise ValueError(
                    f"research gate inputs differ from stored prediction: {details}"
                )
        prediction_ids[security_id] = int(
            cast(int | str, stored["stock_prediction_id"])
        )
    return prediction_ids


def _database_gate_rows(
    rows: Sequence[Mapping[str, object]],
    prediction_ids: Mapping[int, int],
) -> list[dict[str, object]]:
    return [
        {
            "stock_prediction_id": prediction_ids[
                int(cast(int | str, row["security_id"]))
            ],
            **{
                name: row[name]
                for name in _GATE_FIELDS
                if name != "stock_prediction_id"
            },
        }
        for row in rows
    ]


def _normalized_gate(row: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(row.get(name) for name in _GATE_FIELDS)


def _gates_by_identity(
    rows: Sequence[Mapping[str, object]],
) -> dict[tuple[int, int], tuple[object, ...]]:
    return {
        (
            int(cast(int | str, row["stock_prediction_id"])),
            int(cast(int | str, row["gate_order"])),
        ): _normalized_gate(row)
        for row in rows
    }


def persist_research_decision_gates(
    writer: SupabaseResearchWriter,
    *,
    prediction_run_id: int,
    stock_predictions: Sequence[Mapping[str, object]],
    decision_gates: Sequence[Mapping[str, object]],
) -> int:
    """Attach all eight gates after the fail-closed atomic snapshot write."""

    if not decision_gates:
        return 0
    security_ids = [
        int(cast(int | str, value["security_id"])) for value in stock_predictions
    ]
    stored_stocks = _stock_rows(
        writer,
        prediction_run_id=prediction_run_id,
        security_ids=security_ids,
    )
    prediction_ids = _verify_stock_inputs(stock_predictions, stored_stocks)
    rows = _database_gate_rows(decision_gates, prediction_ids)
    returned = writer.upsert(
        "decision_gate_results",
        rows,
        on_conflict="stock_prediction_id,gate_order",
        select=",".join(_GATE_FIELDS),
        return_rows=True,
    )
    expected = _gates_by_identity(rows)
    actual = _gates_by_identity(returned)
    if actual != expected:
        raise ValueError("research decision gate read-back verification failed")
    return len(returned)


__all__ = ["persist_research_decision_gates"]
