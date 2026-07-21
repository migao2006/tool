"""Contracts for raw FinMind datasets that supplement historical daily bars."""

from __future__ import annotations

from dataclasses import dataclass


SUPPLEMENTAL_DATASETS = (
    "adjusted_bars",
    "institutional_flows",
    "margin_short",
)

SUPPLEMENTAL_REASON_CODES = (
    "SOURCE_MARKET_UNAVAILABLE",
    "IDENTITY_UNRESOLVED",
    "POINT_IN_TIME_UNVERIFIED",
    "AVAILABLE_AT_FIRST_RETRIEVAL_ONLY",
    "HISTORICAL_VINTAGE_UNAVAILABLE",
    "RAW_LANDING_ONLY",
)


@dataclass(frozen=True)
class NormalizedHistoricalSupplementalBatch:
    """Every provider row is preserved, including quarantined rows."""

    source_dataset: str
    source_row_count: int
    landing_rows: tuple[dict[str, object], ...]
    quarantine_rows: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        if self.source_dataset not in SUPPLEMENTAL_DATASETS:
            raise ValueError("unsupported supplemental dataset")
        if self.source_row_count != len(self.landing_rows):
            raise ValueError("every source row must have exactly one landing row")
        landing_keys = {row.get("landing_key") for row in self.landing_rows}
        if any(
            issue.get("landing_key") not in landing_keys
            for issue in self.quarantine_rows
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
