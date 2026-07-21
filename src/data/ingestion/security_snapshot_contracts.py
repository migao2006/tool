"""Contracts for current point-in-time security-state snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

from src.data.providers.contracts import ProviderPayload


SECURITY_SNAPSHOT_REASON_CODES = (
    "CURRENT_SECURITY_SNAPSHOT_ONLY",
    "HISTORICAL_SECURITY_IDENTITY_NOT_BACKFILLED",
    "DELISTED_SECURITIES_NOT_BACKFILLED",
    "HISTORICAL_RELEASE_TIMES_UNAVAILABLE",
    "FULL_CASH_DELIVERY_SOURCE_NOT_VERIFIED",
    "INDUSTRY_NAME_MAPPING_NOT_IMPORTED",
    "INTRADAY_SUSPENSIONS_NOT_REPRESENTED",
)
NON_SESSION_REASON = "SNAPSHOT_DATE_NOT_CONFIRMED_BY_BOTH_MARKETS"


@dataclass(frozen=True)
class MarketSnapshotPayloads:
    """The complete current-state source bundle for one exchange."""

    profile: ProviderPayload
    restrictions: ProviderPayload
    suspended: ProviderPayload
    attention: ProviderPayload
    disposals: ProviderPayload


@dataclass(frozen=True)
class NormalizedSecuritySnapshot:
    rows: tuple[dict[str, object], ...]
    profile_date: date
    excluded_intraday_suspensions: int


@dataclass(frozen=True)
class SecuritySnapshotSummary:
    snapshot_date: date
    dry_run: bool
    fetched_records: Mapping[str, int]
    normalized_records: Mapping[str, int]
    excluded_records: Mapping[str, int]
    database_counts: Mapping[str, int]
    source_versions: Mapping[str, str]
    source_dates: Mapping[str, str]
    latest_available_at: datetime
    reason_codes: tuple[str, ...]
    system_status: str = "RESEARCH_ONLY"
    status: str = "PASS"

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_date": self.snapshot_date.isoformat(),
            "dry_run": self.dry_run,
            "fetched_records": dict(self.fetched_records),
            "normalized_records": dict(self.normalized_records),
            "excluded_records": dict(self.excluded_records),
            "database_counts": dict(self.database_counts),
            "source_versions": dict(self.source_versions),
            "source_dates": dict(self.source_dates),
            "latest_available_at": self.latest_available_at.isoformat(),
            "reason_codes": self.reason_codes,
            "system_status": self.system_status,
            "status": self.status,
        }
