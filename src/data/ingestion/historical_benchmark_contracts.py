"""Contracts for the raw FinMind TAIEX total-return benchmark archive."""

from __future__ import annotations

from dataclasses import asdict, dataclass


BENCHMARK_DATASET = "benchmark_total_return"
BENCHMARK_DATA_ID = "TAIEX"
BENCHMARK_REASON_CODES = (
    "POINT_IN_TIME_UNVERIFIED",
    "AVAILABLE_AT_FIRST_RETRIEVAL_ONLY",
    "HISTORICAL_VINTAGE_UNAVAILABLE",
    "RAW_LANDING_ONLY",
    "NOT_EXECUTION_PATH_ALIGNED",
)


@dataclass(frozen=True)
class NormalizedHistoricalBenchmarkBatch:
    """One preserved provider response, including malformed source rows."""

    source_row_count: int
    landing_rows: tuple[dict[str, object], ...]
    quarantine_rows: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        if self.source_row_count != len(self.landing_rows):
            raise ValueError("every source row must have one benchmark landing row")
        landing_keys = {row.get("landing_key") for row in self.landing_rows}
        if any(
            issue.get("landing_key") not in landing_keys
            for issue in self.quarantine_rows
        ):
            raise ValueError("every benchmark issue must reference a landing row")

    @property
    def parsed_count(self) -> int:
        return sum(row.get("parse_status") == "PARSED" for row in self.landing_rows)

    @property
    def quarantined_count(self) -> int:
        return self.source_row_count - self.parsed_count


@dataclass(frozen=True)
class HistoricalBenchmarkLandingResult:
    fetched_rows: int
    archived_rows: int
    quarantined_rows: int
    quarantine_issues: int
    latest_trade_date: str
    source_payload_hash: str
    object_key: str


@dataclass(frozen=True)
class HistoricalBenchmarkBackfillSummary:
    outcome: str
    start_date: str
    end_date: str
    task_id: int | None
    request_count: int
    fetched_rows: int
    archived_rows: int
    quarantined_rows: int
    object_key: str | None
    source_payload_hash: str | None
    reason_codes: tuple[str, ...] = BENCHMARK_REASON_CODES
    point_in_time_status: str = "UNVERIFIED"
    usage_scope: str = "RAW_LANDING_ONLY"
    system_status: str = "RESEARCH_ONLY"

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["reason_codes"] = list(self.reason_codes)
        return result
