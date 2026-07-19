"""Strict conversion of auditable domain values into finite JSON values."""

# pyright: reportAny=false, reportExplicitAny=false, reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from math import isfinite
from typing import Any


def require_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def to_json_safe(value: Any, path: str = "value") -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{path} cannot contain NaN or infinity")
        return value
    if isinstance(value, datetime):
        require_aware_datetime(value, path)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): to_json_safe(item, f"{path}.{key}") for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [
            to_json_safe(item, f"{path}[{index}]") for index, item in enumerate(value)
        ]
    raise TypeError(f"{path} contains unsupported JSON value {type(value).__name__}")


__all__ = ["require_aware_datetime", "to_json_safe"]
