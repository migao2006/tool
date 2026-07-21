"""TAIEX adapter for the shared monthly benchmark OHLC coordinator."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from time import sleep
from typing import Protocol, final
from uuid import UUID

from src.data.providers.twse import TAIEX_MONTHLY_OHLC_DATASET

from .historical_backfill_contracts import HistoricalBackfillTask
from .monthly_benchmark_ohlc_backfill import (
    MonthlyBenchmarkOhlcBackfillCoordinator,
    MonthlyBenchmarkOhlcProfile,
)
from .taiex_ohlc_backfill_contracts import (
    TaiexOhlcBackfillSummary,
    TaiexOhlcLandingResult,
    TaiexOhlcQueueSnapshot,
)
from .taiex_ohlc_contracts import TAIEX_OHLC_SYMBOL


class TaiexOhlcRepository(Protocol):
    def ensure_twse_source(self) -> None: ...

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
    ) -> TaiexOhlcQueueSnapshot: ...


class TaiexOhlcLanding(Protocol):
    def land(
        self,
        *,
        month: date,
        backfill_task_id: int,
    ) -> TaiexOhlcLandingResult: ...


TAIEX_PROFILE = MonthlyBenchmarkOhlcProfile(
    market="TWSE",
    source_dataset=TAIEX_MONTHLY_OHLC_DATASET,
    symbol=TAIEX_OHLC_SYMBOL,
    invalid_scope_reason_code="TAIEX_OHLC_BACKFILL_TASK_SCOPE_INVALID",
    invalid_scope_message="claimed task is outside the official monthly TAIEX scope",
    fetch_failed_reason_code="TAIEX_OHLC_FETCH_FAILED",
)


@final
class TaiexOhlcBackfillCoordinator(
    MonthlyBenchmarkOhlcBackfillCoordinator[
        TaiexOhlcQueueSnapshot,
        TaiexOhlcLandingResult,
        TaiexOhlcBackfillSummary,
    ]
):
    def __init__(
        self,
        *,
        repository: TaiexOhlcRepository,
        landing_service: TaiexOhlcLanding,
        now_fn: Callable[[], datetime] | None = None,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        super().__init__(
            repository=repository,
            landing_service=landing_service,
            ensure_source=repository.ensure_twse_source,
            profile=TAIEX_PROFILE,
            summary_factory=TaiexOhlcBackfillSummary,
            now_fn=now_fn,
            sleep_fn=sleep_fn,
        )
