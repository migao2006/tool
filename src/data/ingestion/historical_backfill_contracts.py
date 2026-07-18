"""Typed contracts for the resumable research-only history backfill."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date

from .contracts import IngestionError


def _required_text(row: Mapping[str, object], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        raise IngestionError(
            "HISTORICAL_BACKFILL_TASK_INVALID",
            f"Backfill task is missing {name}",
        )
    return value.strip()


def _required_int(row: Mapping[str, object], name: str) -> int:
    value = row.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise IngestionError(
            "HISTORICAL_BACKFILL_TASK_INVALID",
            f"Backfill task is missing {name}",
        )
    return value


@dataclass(frozen=True)
class HistoricalBackfillTask:
    task_id: int
    symbol: str
    display_name: str | None
    market: str
    asset_type: str
    priority: int
    start_date: date
    end_date: date
    attempt_count: int
    max_attempts: int

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> "HistoricalBackfillTask":
        market = _required_text(row, "market")
        asset_type = _required_text(row, "asset_type")
        if market not in {"TWSE", "TPEX"} or asset_type not in {
            "COMMON_STOCK",
            "ETF",
        }:
            raise IngestionError(
                "HISTORICAL_BACKFILL_TASK_INVALID",
                "Backfill task contains an unsupported market or asset type",
            )
        try:
            start_date = date.fromisoformat(_required_text(row, "requested_start_date"))
            end_date = date.fromisoformat(_required_text(row, "requested_end_date"))
        except ValueError as error:
            raise IngestionError(
                "HISTORICAL_BACKFILL_TASK_INVALID",
                "Backfill task contains an invalid date range",
            ) from error
        display_name = row.get("display_name")
        return cls(
            task_id=_required_int(row, "task_id"),
            symbol=_required_text(row, "source_symbol"),
            display_name=display_name if isinstance(display_name, str) else None,
            market=market,
            asset_type=asset_type,
            priority=_required_int(row, "priority"),
            start_date=start_date,
            end_date=end_date,
            attempt_count=_required_int(row, "attempt_count"),
            max_attempts=_required_int(row, "max_attempts"),
        )


@dataclass(frozen=True)
class HistoricalBackfillSnapshot:
    database_bytes: int
    landing_bytes: int
    landing_symbols: int
    task_count: int
    twse_common_remaining: int
    tpex_common_remaining: int
    etf_task_count: int
    etf_remaining: int
    succeeded: int
    exhausted: int

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> "HistoricalBackfillSnapshot":
        values = {
            name: _required_int(row, name)
            for name in (
                "database_bytes",
                "landing_bytes",
                "landing_symbols",
                "task_count",
                "twse_common_remaining",
                "tpex_common_remaining",
                "etf_task_count",
                "etf_remaining",
                "succeeded",
                "exhausted",
            )
        }
        return cls(**values)

    @property
    def common_remaining(self) -> int:
        return self.twse_common_remaining + self.tpex_common_remaining


@dataclass(frozen=True)
class HistoricalBackfillSummary:
    outcome: str
    start_date: str
    end_date: str
    attempted_tasks: int
    succeeded_tasks: int
    retried_tasks: int
    fetched_rows: int
    landed_rows: int
    quarantined_rows: int
    quota_remaining_at_start: int
    request_budget: int
    storage_task_budget: int
    database_bytes_before: int
    database_bytes_after: int
    remaining_twse_common: int
    remaining_tpex_common: int
    remaining_etf: int
    exhausted_tasks: int
    reason_codes: tuple[str, ...]
    system_status: str = "RESEARCH_ONLY"
    usage_scope: str = "RAW_LANDING_ONLY"

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["reason_codes"] = list(self.reason_codes)
        return result
