"""Fail-closed assembly of one TWSE five-session research label row."""

# pyright: reportMissingTypeStubs=false, reportUnknownArgumentType=false

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from math import isfinite, sqrt
from zoneinfo import ZoneInfo

import pandas as pd

from src.features.twse_price_volume_schema import (
    TWSE_PRICE_VOLUME_AVAILABILITY_MODES,
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
    TWSE_RESEARCH_SCHEDULING_HINT_REASON,
)
from src.labels.direction_label import (
    NoTradeBandConfig,
    make_direction_label,
    no_trade_band,
)
from src.trading.transaction_cost import TransactionCostModel

from .twse_research_assembly_contracts import ResearchRowExclusion
from .twse_research_assembly_inputs import (
    FEATURE_INPUTS,
    EvidenceInterval,
    ResearchAssemblyInputError,
    aware_timestamp,
    overlap_reasons,
    positive_number,
    reason_codes,
)


HORIZON = 5
LABEL_VERSION = "twse-research-unadjusted-open-close-5d-v1"
TAIPEI = ZoneInfo("Asia/Taipei")


@dataclass(frozen=True)
class RowAssemblyContext:
    bars: pd.DataFrame
    duplicate_bar_keys: set[tuple[str, date]]
    benchmark: dict[date, float]
    duplicate_benchmark_dates: set[date]
    sessions: tuple[date, ...]
    session_positions: dict[date, int]
    actions: tuple[EvidenceInterval, ...]
    suspensions: tuple[EvidenceInterval, ...]
    cost_model: TransactionCostModel
    cost_profile: str
    band_config: NoTradeBandConfig
    duplicate_feature_keys: set[tuple[str, date]]
    benchmark_id: str
    benchmark_version: str
    dataset_snapshot_id: str
    source_hash: str
    research_reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class RowAssemblyOutcome:
    prepared_row: dict[str, object] | None
    exclusion: ResearchRowExclusion | None
    scheduling_hint_used: bool


def _feature_values(feature: dict[str, object], reasons: list[str]) -> dict[str, float]:
    output: dict[str, float] = {}
    for name in FEATURE_INPUTS:
        value = positive_number(feature[name]) if name == "adv20_ntd" else None
        if name != "adv20_ntd":
            try:
                numeric = float(str(feature[name]))
            except (TypeError, ValueError):
                numeric = float("nan")
            value = numeric if isfinite(numeric) else None
        if value is None:
            reasons.append(f"FEATURE_MISSING:{name}")
        else:
            output[name] = value
    return output


def _availability(
    feature: dict[str, object],
    decision_at: datetime,
    reasons: list[str],
) -> tuple[datetime | None, datetime | None, str, bool, tuple[str, ...]]:
    mode = str(feature["availability_mode"])
    limitations = reason_codes(feature["research_limitation_reason_codes"])
    effective_available_at: datetime | None = None
    observed_available_at: datetime | None = None
    try:
        effective_available_at = aware_timestamp(
            feature["effective_available_at"], "effective_available_at"
        )
    except (ResearchAssemblyInputError, ValueError, TypeError):
        reasons.append("FEATURE_AVAILABLE_AT_MISSING")
    try:
        observed_available_at = aware_timestamp(
            feature["observed_available_at"], "observed_available_at"
        )
    except (ResearchAssemblyInputError, ValueError, TypeError):
        reasons.append("FEATURE_OBSERVED_AVAILABLE_AT_MISSING")
    if mode not in TWSE_PRICE_VOLUME_AVAILABILITY_MODES:
        reasons.append("FEATURE_AVAILABILITY_MODE_INVALID")
        return (
            effective_available_at,
            observed_available_at,
            "INVALID",
            False,
            limitations,
        )
    if mode == "STRICT_CANONICAL":
        if limitations:
            reasons.append("STRICT_MODE_RESEARCH_LIMITATION")
        if effective_available_at != observed_available_at:
            reasons.append("STRICT_AVAILABILITY_TIMESTAMP_MISMATCH")
        if observed_available_at is not None and observed_available_at > decision_at:
            reasons.append("POINT_IN_TIME_VIOLATION")
        if not bool(feature["point_in_time_audit_pass"]):
            reasons.append("FEATURE_POINT_IN_TIME_AUDIT_FAILED")
        return (
            effective_available_at,
            observed_available_at,
            "SOURCE_AVAILABLE_AT",
            False,
            limitations,
        )
    if TWSE_RESEARCH_SCHEDULING_HINT_REASON not in limitations:
        reasons.append("SCHEDULING_HINT_LIMITATION_MISSING")
    if effective_available_at is not None and effective_available_at > decision_at:
        reasons.append("SCHEDULING_HINT_AFTER_DECISION")
    return (
        effective_available_at,
        observed_available_at,
        "SCHEDULING_HINT",
        True,
        limitations,
    )


def _path_dates(
    decision_date: date,
    context: RowAssemblyContext,
    reasons: list[str],
) -> tuple[date, ...]:
    position = context.session_positions.get(decision_date)
    if position is None:
        reasons.append("DECISION_SESSION_MISSING")
        return ()
    if position + HORIZON >= len(context.sessions):
        reasons.append("LABEL_WINDOW_INCOMPLETE")
        return ()
    return context.sessions[position + 1 : position + HORIZON + 1]


def _path_reasons(
    *,
    symbol: str,
    decision_date: date,
    path_dates: tuple[date, ...],
    context: RowAssemblyContext,
) -> list[str]:
    reasons: list[str] = []
    exit_date = path_dates[-1] if path_dates else decision_date
    path_keys = [(symbol, session) for session in path_dates]
    if (symbol, decision_date) in context.duplicate_bar_keys or any(
        key in context.duplicate_bar_keys for key in path_keys
    ):
        reasons.append("DUPLICATE_RAW_BAR")
    if (symbol, decision_date) not in context.bars.index:
        reasons.append("DECISION_BAR_MISSING")
    if any(key not in context.bars.index for key in path_keys):
        reasons.append("MISSING_HOLDING_SESSION_BAR")
    existing_keys = [
        key
        for key in ((symbol, decision_date), *path_keys)
        if key in context.bars.index
    ]
    if any(context.bars.loc[key, "market"] != "TWSE" for key in existing_keys):
        reasons.append("TWSE_MARKET_REQUIRED")
    if decision_date in context.duplicate_benchmark_dates or any(
        session in context.duplicate_benchmark_dates for session in path_dates
    ):
        reasons.append("DUPLICATE_BENCHMARK_SESSION")
    if decision_date not in context.benchmark or (
        path_dates and exit_date not in context.benchmark
    ):
        reasons.append("BENCHMARK_WINDOW_MISSING")
    reasons.extend(
        overlap_reasons(
            context.actions,
            symbol=symbol,
            start=decision_date,
            end=exit_date,
        )
    )
    reasons.extend(
        overlap_reasons(
            context.suspensions,
            symbol=symbol,
            start=decision_date,
            end=exit_date,
        )
    )
    return reasons


def assemble_research_row(
    feature: dict[str, object],
    *,
    symbol: str,
    decision_date: date,
    context: RowAssemblyContext,
) -> RowAssemblyOutcome:
    """Build one row or one auditable exclusion, never a silent partial label."""

    if not symbol:
        raise ResearchAssemblyInputError("feature symbols are required")
    reasons: list[str] = []
    if (symbol, decision_date) in context.duplicate_feature_keys:
        reasons.append("DUPLICATE_FEATURE_ROW")
    if str(feature["market"]).upper() != "TWSE":
        reasons.append("TWSE_MARKET_REQUIRED")
    if feature["feature_schema_hash"] != TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH:
        reasons.append("FEATURE_SCHEMA_HASH_MISMATCH")
    if feature["hard_fail"]:
        feature_reasons = reason_codes(feature["hard_fail_reason_codes"])
        reasons.extend(feature_reasons or ("FEATURE_HARD_FAIL",))

    try:
        decision_at = aware_timestamp(feature["decision_at"], "decision_at")
    except (ResearchAssemblyInputError, ValueError):
        reasons.append("DECISION_AT_INVALID")
        decision_at = aware_timestamp(
            datetime.combine(decision_date, time(13, 30), tzinfo=TAIPEI),
            "decision_at",
        )
    local_decision = decision_at.astimezone(TAIPEI)
    if local_decision.date() != decision_date:
        reasons.append("DECISION_DATE_MISMATCH")
    if local_decision.time() < time(13, 30):
        reasons.append("DECISION_NOT_AFTER_CLOSE")

    (
        available_at,
        source_available_at,
        availability_basis,
        used_hint,
        feature_limitations,
    ) = _availability(feature, decision_at, reasons)
    values = _feature_values(feature, reasons)
    path_dates = _path_dates(decision_date, context, reasons)
    reasons.extend(
        _path_reasons(
            symbol=symbol,
            decision_date=decision_date,
            path_dates=path_dates,
            context=context,
        )
    )
    entry_date = path_dates[0] if path_dates else decision_date
    exit_date = path_dates[-1] if path_dates else decision_date
    current_close = (
        positive_number(context.bars.loc[(symbol, decision_date), "close_price"])
        if (symbol, decision_date) in context.bars.index
        else None
    )
    entry_open = (
        positive_number(context.bars.loc[(symbol, entry_date), "open_price"])
        if path_dates and (symbol, entry_date) in context.bars.index
        else None
    )
    exit_close = (
        positive_number(context.bars.loc[(symbol, exit_date), "close_price"])
        if path_dates and (symbol, exit_date) in context.bars.index
        else None
    )
    for value, code in (
        (current_close, "DECISION_CLOSE_INVALID"),
        (entry_open, "ENTRY_OPEN_INVALID"),
        (exit_close, "EXIT_CLOSE_INVALID"),
    ):
        if value is None:
            reasons.append(code)

    cost_rate: float | None = None
    cost_version: str | None = None
    if current_close is not None and "adv20_ntd" in values:
        try:
            estimate = context.cost_model.estimate_for_decision(
                current_price=current_close,
                adv20_ntd=values["adv20_ntd"],
                horizon=HORIZON,
            )
            reasons.extend(estimate.reason_codes)
            profile = estimate.profile(context.cost_profile)
            cost_rate = float(profile.round_trip_cost_rate)
            cost_version = profile.cost_profile_version
        except (KeyError, ValueError, ArithmeticError):
            reasons.append("TRANSACTION_COST_INPUT_INVALID")

    unique_reasons = tuple(dict.fromkeys(reasons))
    if unique_reasons:
        return RowAssemblyOutcome(
            prepared_row=None,
            exclusion=ResearchRowExclusion(symbol, decision_date, unique_reasons),
            scheduling_hint_used=used_hint,
        )
    assert available_at is not None and source_available_at is not None
    assert (
        current_close is not None and entry_open is not None and exit_close is not None
    )
    assert cost_rate is not None and cost_version is not None
    gross_return = exit_close / entry_open - 1
    net_return = gross_return - cost_rate
    benchmark_return = (
        context.benchmark[exit_date] / context.benchmark[decision_date] - 1
    )
    daily_volatility = values["realized_volatility_20"] / sqrt(20)
    direction = make_direction_label(net_return, daily_volatility, context.band_config)
    row_reasons = context.research_reason_codes + feature_limitations
    if used_hint:
        row_reasons += ("SCHEDULING_HINT_NOT_OFFICIAL_PIT",)
    prepared_row: dict[str, object] = {
        "symbol": symbol,
        "market": "TWSE",
        "horizon": HORIZON,
        "decision_date": decision_date,
        "decision_at": decision_at,
        "available_at": available_at,
        "source_latest_available_at": source_available_at,
        "availability_basis": availability_basis,
        "entry_at": datetime.combine(entry_date, time(9), tzinfo=TAIPEI),
        "exit_at": datetime.combine(exit_date, time(13, 30), tzinfo=TAIPEI),
        "gross_return": gross_return,
        "net_return": net_return,
        "benchmark_return": benchmark_return,
        "net_alpha": net_return - benchmark_return,
        "round_trip_cost_rate": cost_rate,
        "cost_profile_version": cost_version,
        "feature_schema_hash": TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
        "label_version": LABEL_VERSION,
        "benchmark_id": context.benchmark_id,
        "benchmark_version": context.benchmark_version,
        "dataset_snapshot_id": context.dataset_snapshot_id,
        "source_hash": context.source_hash,
        "direction": direction.value,
        "direction_no_trade_band": no_trade_band(daily_volatility, context.band_config),
        "no_trade_band_version": context.band_config.version,
        "data_quality_status": "WARN",
        "usage_scope": "MODEL_RESEARCH_ONLY",
        "system_status": "RESEARCH_ONLY",
        "reason_codes": tuple(dict.fromkeys(row_reasons)),
        **values,
    }
    return RowAssemblyOutcome(prepared_row, None, used_hint)


__all__ = [
    "HORIZON",
    "LABEL_VERSION",
    "RowAssemblyContext",
    "assemble_research_row",
]
