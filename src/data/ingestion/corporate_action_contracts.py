"""Immutable contracts for current corporate-action announcements."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime


CORPORATE_ACTION_REASON_CODES = (
    "CURRENT_EX_RIGHTS_FORECAST_ONLY",
    "HISTORICAL_CORPORATE_ACTION_VINTAGES_UNAVAILABLE",
    "CORPORATE_ACTION_ANNOUNCEMENT_TIME_UNKNOWN",
    "FIRST_OBSERVED_AT_USED_FOR_AVAILABILITY",
    "CORPORATE_ACTION_PAYABLE_DATE_UNKNOWN",
    "RIGHTS_COMPONENTS_NOT_IMPORTED",
    "SPLITS_CAPITAL_REDUCTIONS_NOT_IMPORTED",
    "CURRENT_SECURITY_IDENTITY_ONLY",
    "DAILY_BARS_COMPANY_ACTION_COMPLETE_REMAINS_FALSE",
)


@dataclass(frozen=True)
class NormalizedCorporateActions:
    rows: tuple[dict[str, object], ...]
    excluded_unknown_securities: int
    excluded_no_supported_component_rows: int
    omitted_rights_components: int
    unresolved_announced_components: int
    observed_ex_date_min: date | None
    observed_ex_date_max: date | None


@dataclass(frozen=True)
class CorporateActionImportSummary:
    snapshot_date: date
    dry_run: bool
    fetched_records: Mapping[str, int]
    normalized_records: Mapping[str, int]
    excluded_records: Mapping[str, int]
    database_counts: Mapping[str, int]
    source_versions: Mapping[str, str]
    source_dates: Mapping[str, str]
    latest_available_at: datetime
    reason_codes: tuple[str, ...] = CORPORATE_ACTION_REASON_CODES
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
