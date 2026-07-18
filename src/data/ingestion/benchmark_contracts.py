"""Stable contracts for official total-return benchmark observations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime


BENCHMARK_VERSION = "official-total-return-close-v1"
BENCHMARK_REASON_CODES = (
    "CURRENT_MONTH_OFFICIAL_ENDPOINT_ONLY",
    "HISTORICAL_BENCHMARK_VINTAGES_UNAVAILABLE",
    "LABEL_TARGET_ONLY",
    "NOT_EXECUTION_PATH_ALIGNED",
    "BENCHMARK_CLOSE_TO_CLOSE_VS_STOCK_T_PLUS_1_OPEN_TO_H_CLOSE",
    "ROW_PUBLISH_TIME_UNAVAILABLE",
)


@dataclass(frozen=True)
class BenchmarkSpec:
    market: str
    provider: str
    dataset: str
    remote_field: str
    series_code: str


BENCHMARK_SPECS = {
    "TWSE": BenchmarkSpec(
        market="TWSE",
        provider="TWSE",
        dataset="return_index",
        remote_field="TAIEXTotalReturnIndex",
        series_code="TWSE_TOTAL_RETURN_INDEX",
    ),
    "TPEX": BenchmarkSpec(
        market="TPEX",
        provider="TPEX",
        dataset="return_index",
        remote_field="TPExTotalReturnIndex",
        series_code="TPEX_TOTAL_RETURN_INDEX",
    ),
}


@dataclass(frozen=True)
class BenchmarkImportSummary:
    snapshot_date: date
    dry_run: bool
    fetched_records: Mapping[str, int]
    normalized_records: Mapping[str, int]
    database_counts: Mapping[str, int]
    source_versions: Mapping[str, str]
    source_dates: Mapping[str, str]
    latest_available_at: datetime
    reason_codes: tuple[str, ...] = BENCHMARK_REASON_CODES
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
