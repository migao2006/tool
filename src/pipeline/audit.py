"""Common point-in-time audits run before any model or backtest adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .contracts import PipelineBatch, PipelineMode


@dataclass(frozen=True)
class BatchAudit:
    passed: bool
    record_count: int
    reason_codes: tuple[str, ...]
    latest_decision_date: date | None = None


def _frame_columns(records: Any) -> set[str]:
    columns = getattr(records, "columns", ())
    return {str(column) for column in columns}


def audit_batch(
    batch: PipelineBatch,
    *,
    mode: PipelineMode,
    horizon: int,
    as_of_date: date | None,
) -> BatchAudit:
    """Reject empty, cross-horizon, future, or insufficiently identified rows."""

    records = batch.records
    try:
        count = len(records)
    except TypeError:
        return BatchAudit(False, 0, ("UNSIZED_DATASET",))
    if count == 0:
        return BatchAudit(False, 0, ("EMPTY_DATASET",))

    columns = _frame_columns(records)
    required = {"symbol", "horizon", "decision_at", "available_at"}
    missing = sorted(required.difference(columns))
    if missing:
        return BatchAudit(
            False, count, tuple(f"MISSING_COLUMN:{name}" for name in missing)
        )

    try:
        import pandas as pd
    except ModuleNotFoundError:
        return BatchAudit(False, count, ("PANDAS_NOT_INSTALLED",))

    reasons: list[str] = []
    horizon_values: Any = pd.to_numeric(records["horizon"], errors="coerce")
    if horizon_values.isna().any() or not (horizon_values == horizon).all():
        reasons.append("HORIZON_MISMATCH")

    decisions = pd.to_datetime(records["decision_at"], errors="coerce", utc=True)
    available = pd.to_datetime(records["available_at"], errors="coerce", utc=True)
    if decisions.isna().any():
        reasons.append("INVALID_DECISION_AT")
    if available.isna().any():
        reasons.append("INVALID_AVAILABLE_AT")
    if (
        not decisions.isna().any()
        and not available.isna().any()
        and (available > decisions).any()
    ):
        reasons.append("POINT_IN_TIME_VIOLATION")

    if (
        records["symbol"].isna().any()
        or (records["symbol"].astype(str).str.strip() == "").any()
    ):
        reasons.append("INVALID_SYMBOL")
    if (
        mode is PipelineMode.INFER
        and as_of_date is not None
        and not decisions.isna().any()
    ):
        if (decisions.dt.date > as_of_date).any():
            reasons.append("INFERENCE_USES_FUTURE_DECISION")
    latest_decision_date = None
    if not decisions.isna().any():
        latest_decision_date = max(decisions.dt.date)
    return BatchAudit(
        not reasons,
        count,
        tuple(dict.fromkeys(reasons)),
        latest_decision_date,
    )
