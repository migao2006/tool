"""Immutable result contract for historical trading-calendar imports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class CalendarImportSummary:
    requested_start_date: date
    requested_end_date: date
    coverage_start_date: date
    coverage_end_date: date
    dry_run: bool
    markets: tuple[str, ...]
    fetched_dates: int
    normalized_records: int
    database_count: int | None
    observation_database_count: int | None
    source_uri: str
    source_version: str
    source_hash: str
    retrieved_at: datetime
    reason_codes: tuple[str, ...]
    system_status: str = "RESEARCH_ONLY"
    status: str = "PASS"

    def to_dict(self) -> dict[str, object]:
        return {
            "requested_start_date": self.requested_start_date.isoformat(),
            "requested_end_date": self.requested_end_date.isoformat(),
            "coverage_start_date": self.coverage_start_date.isoformat(),
            "coverage_end_date": self.coverage_end_date.isoformat(),
            "dry_run": self.dry_run,
            "markets": self.markets,
            "fetched_dates": self.fetched_dates,
            "normalized_records": self.normalized_records,
            "database_count": self.database_count,
            "observation_database_count": self.observation_database_count,
            "source_uri": self.source_uri,
            "source_version": self.source_version,
            "source_hash": self.source_hash,
            "retrieved_at": self.retrieved_at.isoformat(),
            "reason_codes": self.reason_codes,
            "system_status": self.system_status,
            "status": self.status,
        }
