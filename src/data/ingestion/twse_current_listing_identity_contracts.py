"""Contracts for current MOPS listing-identity research evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


TWSE_CURRENT_LISTING_IDENTITY_REASON_CODES = (
    "CURRENT_MOPS_PROFILE_ONLY",
    "HISTORICAL_IDENTITY_VINTAGE_UNAVAILABLE",
    "OFFICIAL_PUBLICATION_TIME_UNAVAILABLE",
    "FIRST_OBSERVED_AT_RETRIEVAL",
    "ISIN_UNAVAILABLE",
    "SECURITY_ID_NOT_LINKED",
    "SYMBOL_REUSE_NOT_RESOLVED",
)


@dataclass(frozen=True)
class NormalizedTwseCurrentListingIdentities:
    rows: tuple[dict[str, object], ...]
    excluded_non_common_stock_rows: int
    registration_id_rows: int
    listing_date_min: date
    listing_date_max: date


@dataclass(frozen=True)
class TwseCurrentListingIdentityImportSummary:
    snapshot_date: date
    dry_run: bool
    fetched_records: int
    normalized_records: int
    excluded_non_common_stock_rows: int
    registration_id_rows: int
    database_count: int | None
    listing_date_min: date
    listing_date_max: date
    source_version: str
    source_hash: str
    latest_available_at: datetime
    reason_codes: tuple[str, ...] = TWSE_CURRENT_LISTING_IDENTITY_REASON_CODES
    system_status: str = "RESEARCH_ONLY"
    status: str = "PASS"

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_date": self.snapshot_date.isoformat(),
            "dry_run": self.dry_run,
            "fetched_records": self.fetched_records,
            "normalized_records": self.normalized_records,
            "excluded_non_common_stock_rows": self.excluded_non_common_stock_rows,
            "registration_id_rows": self.registration_id_rows,
            "database_count": self.database_count,
            "listing_date_min": self.listing_date_min.isoformat(),
            "listing_date_max": self.listing_date_max.isoformat(),
            "source_version": self.source_version,
            "source_hash": self.source_hash,
            "latest_available_at": self.latest_available_at.isoformat(),
            "reason_codes": self.reason_codes,
            "system_status": self.system_status,
            "status": self.status,
        }
