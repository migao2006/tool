"""Contracts for official delisting registry observations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime


DELISTING_REASON_CODES = (
    "HISTORICAL_IDENTITY_REGISTRY_ONLY",
    "CURRENT_MASTER_NOT_BACKFILLED",
    "HISTORICAL_LISTING_DATE_UNAVAILABLE",
    "HISTORICAL_AVAILABLE_AT_RETRIEVAL_LOWER_BOUND",
    "DELISTING_ANNOUNCEMENT_TIME_UNAVAILABLE",
    "DELISTING_EVENTS_NOT_IDENTITY_RESOLVED",
    "SYMBOL_REUSE_GUARD",
    "SUSPENSION_HISTORY_NOT_IMPORTED",
)


@dataclass(frozen=True)
class NormalizedDelistingRegistry:
    rows: tuple[dict[str, object], ...]
    termination_date_min: date
    termination_date_max: date


@dataclass(frozen=True)
class DelistingRegistrySummary:
    snapshot_date: date
    dry_run: bool
    fetched_records: Mapping[str, int]
    normalized_records: Mapping[str, int]
    database_counts: Mapping[str, int]
    source_versions: Mapping[str, str]
    source_dates: Mapping[str, str]
    latest_available_at: datetime
    reason_codes: tuple[str, ...] = DELISTING_REASON_CODES
    system_status: str = "RESEARCH_ONLY"
    status: str = "PASS"

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_date": self.snapshot_date.isoformat(),
            "dry_run": self.dry_run,
            "fetched_records": dict(self.fetched_records),
            "normalized_records": dict(self.normalized_records),
            "database_counts": dict(self.database_counts),
            "source_versions": dict(self.source_versions),
            "source_dates": dict(self.source_dates),
            "latest_available_at": self.latest_available_at.isoformat(),
            "reason_codes": self.reason_codes,
            "system_status": self.system_status,
            "status": self.status,
        }
