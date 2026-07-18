"""Audit summary contracts for bounded historical daily-bar landing imports."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HistoricalDailyBarImportSummary:
    """Result of a bounded staging import; never a training-readiness claim."""

    dry_run: bool
    start_date: str
    end_date: str
    requested_symbols: tuple[str, ...]
    fetched_rows: int
    landed_rows: int
    quarantined_rows: int
    quarantine_issues: int
    source_payload_hashes: tuple[str, ...]
    database_counts: dict[str, int]
    reason_codes: tuple[str, ...]
    status: str = "RESEARCH_ONLY"
    usage_scope: str = "RAW_LANDING_ONLY"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "dry_run": self.dry_run,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "requested_symbols": list(self.requested_symbols),
            "fetched_rows": self.fetched_rows,
            "landed_rows": self.landed_rows,
            "quarantined_rows": self.quarantined_rows,
            "quarantine_issues": self.quarantine_issues,
            "source_payload_hashes": list(self.source_payload_hashes),
            "database_counts": dict(self.database_counts),
            "usage_scope": self.usage_scope,
            "reason_codes": list(self.reason_codes),
        }
