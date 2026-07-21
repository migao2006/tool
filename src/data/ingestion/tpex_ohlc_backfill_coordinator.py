"""TPEx adapter for the shared monthly benchmark OHLC coordinator."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from time import sleep
from typing import Protocol, final
from uuid import UUID

from src.data.providers.tpex import TPEX_MONTHLY_OHLC_DATASET

from .historical_backfill_contracts import HistoricalBackfillTask
from .monthly_benchmark_ohlc_backfill import (
    MonthlyBenchmarkOhlcBackfillCoordinator,
    MonthlyBenchmarkOhlcProfile,
)
from .tpex_ohlc_backfill_contracts import (
    TpexOhlcBackfillSummary,
    TpexOhlcLandingResult,
    TpexOhlcQueueSnapshot,
)
from .tpex_ohlc_contracts import TPEX_OHLC_SYMBOL


class TpexOhlcRepository(Protocol):
    def ensure_tpex_source(self) -> None: ...

    def seed(
        self,
        *,
        start_month: date,
        end_month: date,
        selection_snapshot_at: datetime,
    ) -> int: ...

    def claim(
        self,
        *,
        worker_id: str,
        claim_token: UUID,
        lease_seconds: int,
    ) -> HistoricalBackfillTask | None: ...

    def complete(
        self,
        *,
        task: HistoricalBackfillTask,
        claim_token: UUID,
        success: bool,
        latest_trade_date: str | None = None,
        fetched_rows: int = 0,
        archived_rows: int = 0,
        retry_after_seconds: int = 900,
        error_code: str | None = None,
    ) -> None: ...

    def snapshot(
        self,
        *,
        start_month: date,
        end_month: date,
    ) -> TpexOhlcQueueSnapshot: ...


class TpexOhlcLanding(Protocol):
    def land(
        self,
        *,
        month: date,
        backfill_task_id: int,
    ) -> TpexOhlcLandingResult: ...


TPEX_PROFILE = MonthlyBenchmarkOhlcProfile(
    market="TPEX",
    source_dataset=TPEX_MONTHLY_OHLC_DATASET,
    symbol=TPEX_OHLC_SYMBOL,
    invalid_scope_reason_code="TPEX_OHLC_BACKFILL_TASK_SCOPE_INVALID",
    invalid_scope_message="claimed task is outside the official monthly TPEx scope",
    fetch_failed_reason_code="TPEX_OHLC_FETCH_FAILED",
)


@final
class TpexOhlcBackfillCoordinator(
    MonthlyBenchmarkOhlcBackfillCoordinator[
        TpexOhlcQueueSnapshot,
        TpexOhlcLandingResult,
        TpexOhlcBackfillSummary,
    ]
):
    def __init__(
        self,
        *,
        repository: TpexOhlcRepository,
        landing_service: TpexOhlcLanding,
        now_fn: Callable[[], datetime] | None = None,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        super().__init__(
            repository=repository,
            landing_service=landing_service,
            ensure_source=repository.ensure_tpex_source,
            profile=TPEX_PROFILE,
            summary_factory=TpexOhlcBackfillSummary,
            now_fn=now_fn,
            sleep_fn=sleep_fn,
        )
