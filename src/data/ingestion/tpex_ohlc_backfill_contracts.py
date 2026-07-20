"""Typed contracts for the official monthly TPEx OHLC backfill."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass

from .contracts import IngestionError
from .tpex_ohlc_contracts import TPEX_OHLC_REASON_CODES


def _nonnegative_int(row: Mapping[str, object], name: str) -> int:
    value = row.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise IngestionError(
            "TPEX_OHLC_BACKFILL_SNAPSHOT_INVALID",
            f"TPEx OHLC queue snapshot contains invalid {name}",
        )
    return value


@dataclass(frozen=True)
class TpexOhlcLandingResult:
    fetched_rows: int
    archived_rows: int
    latest_trade_date: str
    source_payload_hash: str
    object_key: str
    object_created: bool
    byte_size: int


@dataclass(frozen=True)
class TpexOhlcQueueSnapshot:
    task_count: int
    pending: int
    leased: int
    retry: int
    succeeded: int
    exhausted: int
    archive_object_count: int
    archive_row_count: int
    archive_byte_count: int

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> "TpexOhlcQueueSnapshot":
        names = (
            "task_count",
            "pending",
            "leased",
            "retry",
            "succeeded",
            "exhausted",
            "archive_object_count",
            "archive_row_count",
            "archive_byte_count",
        )
        return cls(**{name: _nonnegative_int(row, name) for name in names})

    @property
    def remaining(self) -> int:
        return self.pending + self.leased + self.retry


@dataclass(frozen=True)
class TpexOhlcBackfillSummary:
    outcome: str
    start_month: str
    end_month: str
    attempted_tasks: int
    succeeded_tasks: int
    request_count: int
    fetched_rows: int
    archived_rows: int
    created_objects: int
    reused_objects: int
    archived_bytes: int
    queue: TpexOhlcQueueSnapshot
    reason_codes: tuple[str, ...] = TPEX_OHLC_REASON_CODES
    benchmark_semantics: str = "PRICE_INDEX_NOT_TOTAL_RETURN"
    point_in_time_status: str = "UNVERIFIED"
    usage_scope: str = "RAW_LANDING_ONLY"
    system_status: str = "RESEARCH_ONLY"

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["reason_codes"] = list(self.reason_codes)
        return result
