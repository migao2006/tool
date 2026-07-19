"""Input normalization helpers for TWSE research-label assembly."""

# pyright: reportAny=false, reportMissingTypeStubs=false
# pyright: reportUnknownArgumentType=false, reportUnknownLambdaType=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from math import isfinite

import pandas as pd

from src.features.twse_price_volume_schema import TWSE_PRICE_VOLUME_FEATURE_NAMES


FEATURE_INPUTS = TWSE_PRICE_VOLUME_FEATURE_NAMES


class ResearchAssemblyInputError(ValueError):
    """Raised when an input batch does not meet the assembler schema."""


@dataclass(frozen=True)
class EvidenceInterval:
    symbol: str
    start_date: date
    end_date: date
    reason_code: str


def records(value: object) -> tuple[object, ...]:
    if isinstance(value, pd.DataFrame):
        return tuple(value.to_dict(orient="records"))
    rows = getattr(value, "rows", None)
    if rows is not None:
        return tuple(rows)
    if isinstance(value, Mapping):
        return (value,)
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return tuple(value)
    raise ResearchAssemblyInputError("input must be records or a pandas DataFrame")


def read(record: object, name: str, default: object = None) -> object:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def feature_records(value: object) -> tuple[dict[str, object], ...]:
    output: list[dict[str, object]] = []
    for record in records(value):
        values = read(record, "feature_values", {})
        if values is None:
            values = {}
        if not isinstance(values, Mapping):
            raise ResearchAssemblyInputError("feature_values must be a mapping")
        row = {
            "symbol": read(record, "symbol"),
            "market": read(record, "market", "TWSE"),
            "decision_date": read(record, "decision_date"),
            "decision_at": read(record, "decision_at"),
            "effective_available_at": read(
                record,
                "latest_available_at",
                read(record, "available_at"),
            ),
            "observed_available_at": read(
                record,
                "latest_observed_available_at",
                read(
                    record, "source_latest_available_at", read(record, "available_at")
                ),
            ),
            "availability_mode": read(record, "availability_mode", "STRICT_CANONICAL"),
            "point_in_time_audit_pass": read(record, "point_in_time_audit_pass", False),
            "research_limitation_reason_codes": read(
                record, "research_limitation_reason_codes", ()
            ),
            "hard_fail": read(record, "hard_fail", False),
            "hard_fail_reason_codes": read(record, "hard_fail_reason_codes", ()),
            "feature_schema_hash": read(record, "feature_schema_hash"),
        }
        for name in FEATURE_INPUTS:
            row[name] = values.get(name, read(record, name))
        output.append(row)
    return tuple(output)


def date_value(value: object, name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if type(value) is date:
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as error:
        raise ResearchAssemblyInputError(f"{name} must contain valid dates") from error


def aware_timestamp(value: object, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ResearchAssemblyInputError(
                f"{name} must be timezone-aware"
            ) from error
    else:
        raise ResearchAssemblyInputError(f"{name} must be timezone-aware")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResearchAssemblyInputError(f"{name} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def positive_number(value: object) -> float | None:
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) and number > 0 else None


def reason_codes(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        if value.lstrip().startswith("["):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError as error:
                raise ResearchAssemblyInputError(
                    "reason codes JSON is invalid"
                ) from error
            if not isinstance(decoded, list):
                raise ResearchAssemblyInputError("reason codes JSON must be an array")
            items = tuple(decoded)
        else:
            items = (value,)
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
        items = tuple(value)
    else:
        raise ResearchAssemblyInputError("reason codes must be non-empty strings")
    if any(not isinstance(item, str) or not item for item in items):
        raise ResearchAssemblyInputError("reason codes must be non-empty strings")
    return tuple(dict.fromkeys(str(item) for item in items))


def bar_frame(value: object) -> tuple[pd.DataFrame, set[tuple[str, date]]]:
    frame = pd.DataFrame(records(value))
    required = {"symbol", "market", "trade_date", "open_price", "close_price"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ResearchAssemblyInputError("raw bars missing: " + ", ".join(missing))
    frame = frame.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.strip()
    frame["trade_date"] = frame["trade_date"].map(
        lambda value: date_value(value, "trade_date")
    )
    frame["market"] = frame["market"].astype(str).str.upper()
    for name in ("open_price", "close_price"):
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    duplicates = frame.duplicated(["symbol", "trade_date"], keep=False)
    duplicate_keys = {
        (row.symbol, row.trade_date)
        for row in frame.loc[duplicates, ["symbol", "trade_date"]].itertuples(
            index=False
        )
    }
    frame = frame.loc[~duplicates].set_index(["symbol", "trade_date"], drop=False)
    return frame, duplicate_keys


def benchmark_levels(
    value: object,
) -> tuple[dict[date, float], set[date], tuple[date, ...]]:
    parsed: list[tuple[date, float | None]] = []
    for record in records(value):
        raw_date = read(
            record,
            "session_date",
            read(record, "observation_at", read(record, "trade_date")),
        )
        raw_level = read(
            record,
            "total_return_index",
            read(record, "numeric_value", read(record, "price")),
        )
        if raw_date is None:
            raise ResearchAssemblyInputError("benchmark session date is required")
        parsed.append(
            (
                date_value(raw_date, "benchmark_session_date"),
                positive_number(raw_level),
            )
        )
    date_counts = Counter(session for session, _ in parsed)
    duplicate_dates = {session for session, count in date_counts.items() if count > 1}
    output = {
        session: level
        for session, level in parsed
        if session not in duplicate_dates and level is not None
    }
    sessions = tuple(sorted(date_counts))
    return output, duplicate_dates, sessions


def intervals(
    value: object | None, default_reason: str
) -> tuple[EvidenceInterval, ...]:
    if value is None:
        return ()
    output: list[EvidenceInterval] = []
    for record in records(value):
        symbol = str(read(record, "symbol", "")).strip()
        start = date_value(read(record, "start_date"), "start_date")
        end = date_value(read(record, "end_date"), "end_date")
        reason = str(read(record, "reason_code", default_reason)).strip()
        if not symbol or start > end:
            raise ResearchAssemblyInputError("evidence intervals are invalid")
        output.append(EvidenceInterval(symbol, start, end, reason or default_reason))
    return tuple(output)


def overlap_reasons(
    evidence: tuple[EvidenceInterval, ...],
    *,
    symbol: str,
    start: date,
    end: date,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            interval.reason_code
            for interval in evidence
            if interval.symbol == symbol
            and interval.start_date <= end
            and interval.end_date >= start
        )
    )


def empty_prepared() -> pd.DataFrame:
    columns = (
        "symbol",
        "market",
        "horizon",
        "decision_date",
        "decision_at",
        "available_at",
        "entry_at",
        "exit_at",
        "gross_return",
        "net_return",
        "benchmark_return",
        "net_alpha",
        "round_trip_cost_rate",
        "direction",
        "feature_schema_hash",
        "label_version",
        "benchmark_id",
        "benchmark_version",
        "cost_profile_version",
        "dataset_snapshot_id",
        "source_hash",
        *FEATURE_INPUTS,
    )
    return pd.DataFrame(
        {name: pd.Series(dtype="object") for name in dict.fromkeys(columns)}
    )


__all__ = [
    "FEATURE_INPUTS",
    "ResearchAssemblyInputError",
    "aware_timestamp",
    "bar_frame",
    "benchmark_levels",
    "date_value",
    "empty_prepared",
    "feature_records",
    "intervals",
    "overlap_reasons",
    "positive_number",
    "reason_codes",
]
