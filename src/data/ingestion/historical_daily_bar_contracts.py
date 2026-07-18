"""Immutable contracts for unresolved historical daily-bar landing rows."""

from __future__ import annotations

from dataclasses import dataclass


HISTORICAL_DAILY_BAR_REASON_CODES = (
    "SOURCE_MARKET_UNAVAILABLE",
    "IDENTITY_UNRESOLVED",
    "POINT_IN_TIME_UNVERIFIED",
    "AVAILABLE_AT_FIRST_RETRIEVAL_ONLY",
    "RAW_LANDING_ONLY",
)


@dataclass(frozen=True)
class NormalizedHistoricalDailyBarBatch:
    """Every provider row lands; hard failures also receive issue records."""

    source_row_count: int
    landing_rows: tuple[dict[str, object], ...]
    quarantine_rows: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        if self.source_row_count != len(self.landing_rows):
            raise ValueError("every source row must have exactly one landing row")
        landing_keys = {row.get("landing_key") for row in self.landing_rows}
        if any(
            row.get("landing_key") not in landing_keys for row in self.quarantine_rows
        ):
            raise ValueError("every quarantine issue must reference a landing row")

    @property
    def parsed_count(self) -> int:
        return sum(row.get("parse_status") == "PARSED" for row in self.landing_rows)

    @property
    def quarantined_count(self) -> int:
        return sum(
            row.get("parse_status") == "QUARANTINED" for row in self.landing_rows
        )
