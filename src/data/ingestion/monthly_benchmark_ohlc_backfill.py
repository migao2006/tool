"""Shared orchestration for bounded monthly benchmark OHLC backfills."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from time import sleep
from typing import Generic, Protocol, TypeVar
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from src.data.providers.errors import ProviderError

from .contracts import IngestionError
from .historical_backfill_contracts import HistoricalBackfillTask


TAIPEI = ZoneInfo("Asia/Taipei")


class MonthlyBenchmarkQueueSnapshot(Protocol):
    exhausted: int

    @property
    def remaining(self) -> int: ...


class MonthlyBenchmarkLandingResult(Protocol):
    latest_trade_date: str
    fetched_rows: int
    archived_rows: int
    byte_size: int
    object_created: bool


QueueT = TypeVar("QueueT", bound=MonthlyBenchmarkQueueSnapshot)
LandingT = TypeVar("LandingT", bound=MonthlyBenchmarkLandingResult)
SummaryT = TypeVar("SummaryT")


class MonthlyBenchmarkRepository(Protocol[QueueT]):
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
    ) -> QueueT: ...


class MonthlyBenchmarkLanding(Protocol[LandingT]):
    def land(
        self,
        *,
        month: date,
        backfill_task_id: int,
    ) -> LandingT: ...


class MonthlyBenchmarkSummaryFactory(Protocol[QueueT, SummaryT]):
    def __call__(
        self,
        *,
        outcome: str,
        start_month: str,
        end_month: str,
        attempted_tasks: int,
        succeeded_tasks: int,
        request_count: int,
        fetched_rows: int,
        archived_rows: int,
        created_objects: int,
        reused_objects: int,
        archived_bytes: int,
        queue: QueueT,
    ) -> SummaryT: ...


@dataclass(frozen=True)
class MonthlyBenchmarkOhlcProfile:
    market: str
    source_dataset: str
    symbol: str
    invalid_scope_reason_code: str
    invalid_scope_message: str
    fetch_failed_reason_code: str


@dataclass
class _RunCounters:
    attempted: int = 0
    succeeded: int = 0
    fetched: int = 0
    archived: int = 0
    created: int = 0
    reused: int = 0
    archived_bytes: int = 0

    def record(self, result: MonthlyBenchmarkLandingResult) -> None:
        self.succeeded += 1
        self.fetched += result.fetched_rows
        self.archived += result.archived_rows
        self.archived_bytes += result.byte_size
        if result.object_created:
            self.created += 1
        else:
            self.reused += 1


def _month_end(month: date) -> date:
    return month.replace(day=monthrange(month.year, month.month)[1])


class MonthlyBenchmarkOhlcBackfillCoordinator(Generic[QueueT, LandingT, SummaryT]):
    """Execute the venue-neutral monthly OHLC queue lifecycle."""

    def __init__(
        self,
        *,
        repository: MonthlyBenchmarkRepository[QueueT],
        landing_service: MonthlyBenchmarkLanding[LandingT],
        ensure_source: Callable[[], None],
        profile: MonthlyBenchmarkOhlcProfile,
        summary_factory: MonthlyBenchmarkSummaryFactory[QueueT, SummaryT],
        now_fn: Callable[[], datetime] | None = None,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        self.repository = repository
        self.landing_service = landing_service
        self.ensure_source = ensure_source
        self.profile = profile
        self.summary_factory = summary_factory
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
    ) -> SummaryT:
        now = self._validate_request(
            start_month=start_month,
            end_month=end_month,
            worker_id=worker_id,
            max_tasks=max_tasks,
            request_interval_seconds=request_interval_seconds,
            lease_seconds=lease_seconds,
        )
        self.ensure_source()
        _ = self.repository.seed(
            start_month=start_month,
            end_month=end_month,
            selection_snapshot_at=now,
        )
        counters = self._process_tasks(
            start_month=start_month,
            end_month=end_month,
            worker_id=worker_id,
            max_tasks=max_tasks,
            request_interval_seconds=request_interval_seconds,
            lease_seconds=lease_seconds,
            retry_after_seconds=retry_after_seconds,
        )
        queue = self.repository.snapshot(
            start_month=start_month,
            end_month=end_month,
        )
        return self.summary_factory(
            outcome=self._outcome(queue, counters.attempted),
            start_month=start_month.isoformat(),
            end_month=end_month.isoformat(),
            attempted_tasks=counters.attempted,
            succeeded_tasks=counters.succeeded,
            request_count=counters.attempted,
            fetched_rows=counters.fetched,
            archived_rows=counters.archived,
            created_objects=counters.created,
            reused_objects=counters.reused,
            archived_bytes=counters.archived_bytes,
            queue=queue,
        )

    def _validate_request(
        self,
        *,
        start_month: date,
        end_month: date,
        worker_id: str,
        max_tasks: int,
        request_interval_seconds: float,
        lease_seconds: int,
    ) -> datetime:
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
        return now

    def _process_tasks(
        self,
        *,
        start_month: date,
        end_month: date,
        worker_id: str,
        max_tasks: int,
        request_interval_seconds: float,
        lease_seconds: int,
        retry_after_seconds: int,
    ) -> _RunCounters:
        counters = _RunCounters()
        for task_index in range(max_tasks):
            claim_token = uuid4()
            task = self.repository.claim(
                worker_id=worker_id,
                claim_token=claim_token,
                lease_seconds=lease_seconds,
            )
            if task is None:
                break
            self._assert_task_scope(
                task,
                claim_token=claim_token,
                start_month=start_month,
                end_month=end_month,
                retry_after_seconds=retry_after_seconds,
            )
            if task_index:
                self.sleep_fn(request_interval_seconds)
            counters.attempted += 1
            result = self._land_task(
                task,
                claim_token=claim_token,
                retry_after_seconds=retry_after_seconds,
            )
            counters.record(result)
        return counters

    def _assert_task_scope(
        self,
        task: HistoricalBackfillTask,
        *,
        claim_token: UUID,
        start_month: date,
        end_month: date,
        retry_after_seconds: int,
    ) -> None:
        valid = (
            task.source_dataset == self.profile.source_dataset
            and task.symbol == self.profile.symbol
            and task.market == self.profile.market
            and task.asset_type == "BENCHMARK"
            and task.start_date.day == 1
            and task.end_date == _month_end(task.start_date)
            and start_month <= task.start_date <= end_month
        )
        if valid:
            return
        self.repository.complete(
            task=task,
            claim_token=claim_token,
            success=False,
            retry_after_seconds=retry_after_seconds,
            error_code=self.profile.invalid_scope_reason_code,
        )
        raise IngestionError(
            self.profile.invalid_scope_reason_code,
            self.profile.invalid_scope_message,
        )

    def _land_task(
        self,
        task: HistoricalBackfillTask,
        *,
        claim_token: UUID,
        retry_after_seconds: int,
    ) -> LandingT:
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
                error_code=getattr(
                    error,
                    "reason_code",
                    self.profile.fetch_failed_reason_code,
                ),
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
        return result

    @staticmethod
    def _outcome(queue: MonthlyBenchmarkQueueSnapshot, attempted: int) -> str:
        if queue.exhausted:
            return "BLOCKED"
        if queue.remaining == 0:
            return "COMPLETE"
        if attempted:
            return "PARTIAL"
        return "DEFERRED"
