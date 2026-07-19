"""Explicit availability policies for auditable TWSE research features."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from .twse_price_volume_schema import (
    TWSE_PRICE_VOLUME_AVAILABILITY_MODES,
    TWSE_RESEARCH_SCHEDULING_HINT_REASON,
)


AvailabilityMode = Literal["STRICT_CANONICAL", "RESEARCH_SCHEDULING_HINT"]
RESEARCH_SCHEDULING_HINT_CUTOFF = time(16, 0)
TAIPEI = ZoneInfo("Asia/Taipei")

_FIRST_OBSERVED_RESEARCH_LIMITATIONS = frozenset(
    {
        "BAR_AVAILABLE_AFTER_DECISION",
        "CANONICAL_POINT_IN_TIME_UNVERIFIED",
        "POINT_IN_TIME_UNVERIFIED",
        "RAW_AVAILABLE_AT_FIRST_OBSERVED_ONLY",
        "RAW_POINT_IN_TIME_UNVERIFIED",
        "ROW_POINT_IN_TIME_UNVERIFIED",
    }
)


@dataclass(frozen=True)
class AvailabilityResolution:
    observed_at: datetime
    effective_at: datetime
    hard_fail_reason_codes: tuple[str, ...]
    research_limitation_reason_codes: tuple[str, ...]


def validate_availability_mode(value: str) -> AvailabilityMode:
    if value not in TWSE_PRICE_VOLUME_AVAILABILITY_MODES:
        raise ValueError("unsupported TWSE feature availability mode")
    return value


def resolve_availability(
    *,
    observed_at: datetime,
    trade_date: date,
    available_at_basis: str | None,
    availability_mode: AvailabilityMode,
    evidence_reason_codes: tuple[str, ...] = (),
) -> AvailabilityResolution:
    """Resolve effective time without rewriting the observed evidence timestamp."""

    hard_reasons = list(evidence_reason_codes)
    limitations: list[str] = []
    effective_at = observed_at
    uses_hint = (
        availability_mode == "RESEARCH_SCHEDULING_HINT"
        and available_at_basis == "FIRST_OBSERVED_AT_RETRIEVAL"
    )
    if availability_mode == "RESEARCH_SCHEDULING_HINT" and available_at_basis is None:
        hard_reasons.append("RESEARCH_SCHEDULING_HINT_BASIS_REQUIRED")
    if uses_hint:
        effective_at = datetime.combine(
            trade_date,
            RESEARCH_SCHEDULING_HINT_CUTOFF,
            tzinfo=TAIPEI,
        )
        limitations.append(TWSE_RESEARCH_SCHEDULING_HINT_REASON)
    return AvailabilityResolution(
        observed_at=observed_at,
        effective_at=effective_at,
        hard_fail_reason_codes=tuple(dict.fromkeys(hard_reasons)),
        research_limitation_reason_codes=tuple(limitations),
    )


def partition_source_reasons(
    reason_codes: tuple[str, ...],
    *,
    availability_mode: AvailabilityMode,
    available_at_basis: str | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Downgrade only the frozen first-observed research allowlist."""

    can_downgrade = (
        availability_mode == "RESEARCH_SCHEDULING_HINT"
        and available_at_basis == "FIRST_OBSERVED_AT_RETRIEVAL"
    )
    hard: list[str] = []
    limitations: list[str] = []
    for reason in reason_codes:
        if can_downgrade and reason in _FIRST_OBSERVED_RESEARCH_LIMITATIONS:
            limitations.append(reason)
        else:
            hard.append(reason)
    return tuple(dict.fromkeys(hard)), tuple(dict.fromkeys(limitations))


__all__ = [
    "AvailabilityMode",
    "AvailabilityResolution",
    "RESEARCH_SCHEDULING_HINT_CUTOFF",
    "partition_source_reasons",
    "resolve_availability",
    "validate_availability_mode",
]
