"""Duck-typed canonical record and dataframe adaptation helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from math import isfinite
from typing import cast


MISSING = object()


def read_field(record: object, field_name: str) -> object:
    if isinstance(record, Mapping):
        return cast(Mapping[object, object], record).get(field_name, MISSING)
    return getattr(record, field_name, MISSING)


def required_text(record: object, field_name: str) -> str:
    value = read_field(record, field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def date_value(value: object, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if type(value) is date:
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO date") from error


def datetime_value(value: object, field_name: str) -> datetime:
    try:
        parsed = (
            value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        )
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def optional_number(
    record: object,
    field_name: str,
    *,
    nonnegative: bool,
) -> tuple[float | None, tuple[str, ...]]:
    raw = read_field(record, field_name)
    if raw is MISSING or raw is None or isinstance(raw, bool):
        return None, (f"FEATURE_INPUT_INVALID:{field_name}",)
    try:
        value = float(str(raw))
    except (TypeError, ValueError):
        return None, (f"FEATURE_INPUT_INVALID:{field_name}",)
    minimum_ok = value >= 0 if nonnegative else value > 0
    if not isfinite(value) or not minimum_ok:
        return None, (f"FEATURE_INPUT_INVALID:{field_name}",)
    return value, ()


def source_reason_codes(record: object) -> tuple[str, ...]:
    value = read_field(record, "reason_codes")
    if value is MISSING or value is None:
        return ()
    if not isinstance(value, (tuple, list)):
        raise ValueError("reason_codes must be a sequence of non-empty strings")
    raw_reasons = cast(Sequence[object], value)
    if any(not isinstance(reason, str) or not reason for reason in raw_reasons):
        raise ValueError("reason_codes must be a sequence of non-empty strings")
    reasons = cast(Sequence[str], raw_reasons)
    return tuple(dict.fromkeys(reasons))


def market_value(record: object) -> str:
    raw = read_field(record, "market")
    if raw is MISSING:
        raise ValueError("market is required")
    return str(getattr(raw, "value", raw)).strip()


def observed_available_at(record: object) -> tuple[datetime, tuple[str, ...]]:
    candidates = [
        datetime_value(value, name)
        for value, name in (
            (read_field(record, "available_at"), "available_at"),
            (read_field(record, "raw_available_at"), "raw_available_at"),
        )
        if value is not MISSING and value is not None
    ]
    if not candidates:
        raise ValueError("available_at or raw_available_at is required")
    reasons = () if len(set(candidates)) == 1 else ("AVAILABLE_AT_CONFLICT",)
    return max(candidates), reasons


def available_at_basis(record: object) -> tuple[str | None, tuple[str, ...]]:
    candidates = tuple(
        str(value).strip()
        for value in (
            read_field(record, "available_at_basis"),
            read_field(record, "raw_available_at_basis"),
        )
        if value is not MISSING and value is not None and str(value).strip()
    )
    if not candidates:
        return None, ()
    reasons: list[str] = []
    if len(set(candidates)) != 1:
        reasons.append("AVAILABLE_AT_BASIS_CONFLICT")
    basis = candidates[-1]
    if basis not in {
        "FIRST_OBSERVED_AT_RETRIEVAL",
        "OFFICIAL_PUBLICATION_AT",
        "VERSIONED_SNAPSHOT",
    }:
        reasons.append("AVAILABLE_AT_BASIS_INVALID")
    return basis, tuple(reasons)


def materialize_records(records: object) -> tuple[object, ...]:
    if isinstance(records, Mapping):
        normalized_record = cast(Mapping[str, object], records)
        return (normalized_record,)
    to_dict = getattr(records, "to_dict", None)
    columns = getattr(records, "columns", None)
    if callable(to_dict) and columns is not None:
        materialized = to_dict(orient="records")
        if not isinstance(materialized, list):
            raise ValueError("dataframe to_dict must return record rows")
        return tuple(cast(list[object], materialized))
    if isinstance(records, Iterable) and not isinstance(records, (str, bytes)):
        return tuple(records)
    raise TypeError("records must be canonical bar records or a dataframe")


__all__ = [
    "MISSING",
    "available_at_basis",
    "date_value",
    "market_value",
    "materialize_records",
    "observed_available_at",
    "optional_number",
    "read_field",
    "required_text",
    "source_reason_codes",
]
