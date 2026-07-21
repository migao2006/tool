"""Input validation shared by provider clients."""

from __future__ import annotations

from collections.abc import Collection
from datetime import date
import re


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._:/^=-]{1,64}$")
PATH_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9._^-]{1,32}$")
DATASET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,96}$")


def require_identifier(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not IDENTIFIER_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field} contains unsupported characters")
    return normalized


def require_path_segment(value: str, *, field: str) -> str:
    normalized = value.strip()
    if normalized in {".", ".."} or not PATH_SEGMENT_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field} contains unsupported path characters")
    return normalized


def require_dataset(value: str, allowed: Collection[str]) -> str:
    normalized = value.strip()
    if not DATASET_PATTERN.fullmatch(normalized) or normalized not in allowed:
        raise ValueError(f"unsupported provider dataset: {value}")
    return normalized


def iso_date(value: date | str | None, *, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise ValueError(f"{field} must use YYYY-MM-DD") from error


def iso_date_range(
    start: date | str | None,
    end: date | str | None,
) -> tuple[str | None, str | None]:
    normalized_start = iso_date(start, field="start_date")
    normalized_end = iso_date(end, field="end_date")
    if normalized_start and normalized_end and normalized_start > normalized_end:
        raise ValueError("start_date must not be after end_date")
    return normalized_start, normalized_end
