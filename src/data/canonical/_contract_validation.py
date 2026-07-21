"""Shared primitive validation for canonical data contracts."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from zoneinfo import ZoneInfo


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MARKETS = frozenset({"TWSE", "TPEX"})
TAIPEI = ZoneInfo("Asia/Taipei")


def utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def digest(value: str, field: str) -> str:
    normalized = value.strip().lower()
    if not SHA256_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field} must be a SHA-256 digest")
    return normalized


def required_text(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized
