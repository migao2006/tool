"""Coordinate a bounded, paced run of monthly official TAIEX OHLC tasks."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Callable
from datetime import date, datetime, timezone
from time import sleep
from typing import Protocol, final
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from src.data.providers.errors import ProviderError
from src.data.providers.twse import TAIEX_MONTHLY_OHLC_DATASET

from .contracts import IngestionError
from .historical_backfill_contracts import HistoricalBackfillTask
from .taiex_ohlc_backfill_contracts import (
    TaiexOhlcBackfillSummary,
    TaiexOhlcLandingResult,
    TaiexOhlcQueueSnapshot,
)
from .taiex_ohlc_contracts import TAIEX_OHLC_SYMBOL


TAIPEI = ZoneInfo("Asia/Taipei")


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


def _month_end(month: date) -> date:
    return month.replace(day=monthrange(month.year, month.month)[1])


def _valid_task(
    task: HistoricalBackfillTask,
    *,
    start_month: date,
    end_month: date,
) -> bool:
    return (
        task.source_dataset == TAIEX_MONTHLY_OHLC_DATASET
        and task.symbol == TAIEX_OHLC_SYMBOL
        and task.market == "TWSE"
        and task.asset_type == "BENCHMARK"
        and task.start_date.day == 1
        and task.end_date == _month_end(task.start_date)
        and start_month <= task.start_date <= end_month
    )


@final
class TaiexOhlcBackfillCoordinator:
    def __init__(
        self,
        *,
        repository: TaiexOhlcRepository,
        landing_service: TaiexOhlcLanding,
        now_fn: Callable[[], datetime] | None = None,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        self.repository = repository
        self.landing_service = landing_service
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.sleep_fn = sleep_fn

    def run(
        self,
        *,
        start_month: date,
        end_month: date,
        worker_id: str,
        max_tasks: int,
        request_interval_seconds: float,
        lease_seconds: int = 900,
        retry_after_seconds: int = 900,
    ) -> TaiexOhlcBackfillSummary:
        now = self.now_fn()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now_fn must return a timezone-aware datetime")
        if (
            start_month.day != 1
            or end_month.day != 1
            or start_month > end_month
            or end_month >= now.astimezone(TAIPEI).date().replace(day=1)
        ):
            raise ValueError("only completed Gregorian first-of-month bounds are valid")
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        if not 1 <= max_tasks <= 24:
            raise ValueError("max_tasks must be between 1 and 24")
        if not 0.5 <= request_interval_seconds <= 30:
            raise ValueError("request interval must be between 0.5 and 30 seconds")
        if not 60 <= lease_seconds <= 1800:
            raise ValueError("lease_seconds must be between 60 and 1800")

        self.repository.ensure_twse_source()
        _ = self.repository.seed(
            start_month=start_month,
            end_month=end_month,
            selection_snapshot_at=now,
        )
        attempted = succeeded = fetched = archived = 0
        created = reused = archived_bytes = 0
        for task_index in range(max_tasks):
            claim_token = uuid4()
            task = self.repository.claim(
                worker_id=worker_id,
                claim_token=claim_token,
                lease_seconds=lease_seconds,
            )
            if task is None:
                break
            if not _valid_task(
                task,
                start_month=start_month,
                end_month=end_month,
            ):
                self.repository.complete(
                    task=task,
                    claim_token=claim_token,
                    success=False,
                    retry_after_seconds=retry_after_seconds,
                    error_code="TAIEX_OHLC_BACKFILL_TASK_SCOPE_INVALID",
                )
                raise IngestionError(
                    "TAIEX_OHLC_BACKFILL_TASK_SCOPE_INVALID",
                    "claimed task is outside the official monthly TAIEX scope",
                )
            if task_index:
                self.sleep_fn(request_interval_seconds)
            attempted += 1
            try:
                result = self.landing_service.land(
                    month=task.start_date,
                    backfill_task_id=task.task_id,
                )
            except (IngestionError, ProviderError) as error:
                self.repository.complete(
                    task=task,
                    claim_token=claim_token,
                    success=False,
                    retry_after_seconds=retry_after_seconds,
                    error_code=getattr(error, "reason_code", "TAIEX_OHLC_FETCH_FAILED"),
                )
                raise
            self.repository.complete(
                task=task,
                claim_token=claim_token,
                success=True,
                latest_trade_date=result.latest_trade_date,
                fetched_rows=result.fetched_rows,
                archived_rows=result.archived_rows,
                retry_after_seconds=retry_after_seconds,
            )
            succeeded += 1
            fetched += result.fetched_rows
            archived += result.archived_rows
            archived_bytes += result.byte_size
            if result.object_created:
                created += 1
            else:
                reused += 1

        queue = self.repository.snapshot(
            start_month=start_month,
            end_month=end_month,
        )
        if queue.exhausted:
            outcome = "BLOCKED"
        elif queue.remaining == 0:
            outcome = "COMPLETE"
        elif attempted:
            outcome = "PARTIAL"
        else:
            outcome = "DEFERRED"
        return TaiexOhlcBackfillSummary(
            outcome=outcome,
            start_month=start_month.isoformat(),
            end_month=end_month.isoformat(),
            attempted_tasks=attempted,
            succeeded_tasks=succeeded,
            request_count=attempted,
            fetched_rows=fetched,
            archived_rows=archived,
            created_objects=created,
            reused_objects=reused,
            archived_bytes=archived_bytes,
            queue=queue,
        )
