"""Quota-, time-, and capacity-aware coordinator for historical landing data."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from time import monotonic, sleep
from typing import final
from uuid import UUID, uuid4

from src.data.providers.errors import (
    ProviderConfigurationError,
    ProviderCredentialError,
    ProviderError,
    ProviderHttpError,
)

from .contracts import IngestionError
from .historical_backfill_contracts import (
    HistoricalBackfillSnapshot,
    HistoricalBackfillSummary,
    HistoricalBackfillTask,
)
from .historical_backfill_runtime import (
    BackfillLandingService,
    BackfillProvider,
    BackfillRepository,
    finmind_quota_counters,
    is_quota_error,
    storage_task_budget,
)
from .historical_backfill_settings import HistoricalBackfillSettings
from .historical_backfill_universe import finmind_etf_schedule_rows
from .historical_daily_bar_import_contracts import HistoricalSymbolLandingResult


@dataclass(frozen=True)
class _RunWindow:
    start_date: date
    end_date: date
    selection_snapshot_at: datetime
    deadline: float


@dataclass
class _RunBudget:
    quota_used: int
    quota_limit: int
    request_budget: int
    storage_budget: int
    pacing_seconds: float


@dataclass
class _RunCounters:
    attempted: int = 0
    succeeded: int = 0
    retried: int = 0
    fetched_rows: int = 0
    landed_rows: int = 0
    quarantined_rows: int = 0

    def record_success(self, result: HistoricalSymbolLandingResult) -> None:
        self.succeeded += 1
        self.fetched_rows += result.fetched_rows
        self.landed_rows += result.landed_rows
        self.quarantined_rows += result.quarantined_rows


@dataclass
class _StopFlags:
    quota: bool = False
    time: bool = False
    capacity: bool = False


@final
class HistoricalBackfillCoordinator:
    """Run one resumable batch while preserving strict market-stage priority."""

    def __init__(
        self,
        *,
        provider: BackfillProvider,
        repository: BackfillRepository,
        landing_service: BackfillLandingService,
        settings: HistoricalBackfillSettings,
        sleep_fn: Callable[[float], None] = sleep,
        monotonic_fn: Callable[[], float] = monotonic,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.provider = provider
        self.repository = repository
        self.landing_service = landing_service
        self.settings = settings
        self._sleep = sleep_fn
        self._monotonic = monotonic_fn
        self._now = now_fn or (lambda: datetime.now(timezone.utc))

    def _paced_wait(
        self, *, last_request_at: float, pacing_seconds: float, deadline: float
    ) -> bool:
        wait_seconds = max(pacing_seconds - (self._monotonic() - last_request_at), 0)
        if self._monotonic() + wait_seconds >= deadline:
            return False
        if wait_seconds:
            self._sleep(wait_seconds)
        return True

    def run(
        self,
        *,
        start_date: date,
        end_date: date,
        max_tasks: int,
        worker_id: str,
    ) -> HistoricalBackfillSummary:
        window = self._prepare_window(
            start_date=start_date,
            end_date=end_date,
            max_tasks=max_tasks,
            worker_id=worker_id,
        )
        before = self._initialize_queue(window)
        last_request_started_at = self._monotonic()
        try:
            budget = self._load_budget(before)
        except ProviderHttpError as error:
            if not is_quota_error(error):
                raise
            return self._quota_wait_summary(window, before)

        before, last_request_started_at = self._seed_etfs_if_ready(
            window=window,
            before=before,
            budget=budget,
            last_request_started_at=last_request_started_at,
        )
        counters, stops = self._process_claimed_tasks(
            window=window,
            max_tasks=max_tasks,
            worker_id=worker_id,
            budget=budget,
            last_request_started_at=last_request_started_at,
        )
        if counters.succeeded and self.settings.refresh_home_status:
            self.landing_service.refresh_home_status()
        after = self.repository.snapshot(
            start_date=window.start_date,
            end_date=window.end_date,
        )
        outcome = self._outcome(
            counters=counters,
            stops=stops,
            budget=budget,
            after=after,
        )
        return self._summary(
            window=window,
            before=before,
            after=after,
            budget=budget,
            counters=counters,
            outcome=outcome,
        )

    def _prepare_window(
        self,
        *,
        start_date: date,
        end_date: date,
        max_tasks: int,
        worker_id: str,
    ) -> _RunWindow:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if not 1 <= max_tasks <= 100:
            raise ValueError("max_tasks must be between 1 and 100")
        if not worker_id.strip() or len(worker_id) > 128:
            raise ValueError("worker_id must contain 1 to 128 characters")
        started_at = self._monotonic()
        selection_snapshot_at = self._now()
        if selection_snapshot_at.tzinfo is None:
            raise ValueError("now_fn must return a timezone-aware datetime")
        return _RunWindow(
            start_date=start_date,
            end_date=end_date,
            selection_snapshot_at=selection_snapshot_at,
            deadline=started_at + self.settings.max_runtime_seconds,
        )

    def _initialize_queue(self, window: _RunWindow) -> HistoricalBackfillSnapshot:
        self.repository.ensure_finmind_source()
        if self.settings.seed_common_tasks:
            _ = self.repository.seed_common(
                start_date=window.start_date,
                end_date=window.end_date,
                selection_snapshot_at=window.selection_snapshot_at,
            )
        if self.settings.seed_common_tasks and self.settings.seed_delisted_tasks:
            _ = self.repository.seed_delisted_common(
                start_date=window.start_date,
                end_date=window.end_date,
                selection_snapshot_at=window.selection_snapshot_at,
            )
        return self.repository.snapshot(
            start_date=window.start_date,
            end_date=window.end_date,
        )

    def _load_budget(self, before: HistoricalBackfillSnapshot) -> _RunBudget:
        quota_payload = self.provider.fetch_quota()
        quota_used, quota_limit = finmind_quota_counters(quota_payload)
        return _RunBudget(
            quota_used=quota_used,
            quota_limit=quota_limit,
            request_budget=max(
                quota_limit - quota_used - self.settings.quota_reserve,
                0,
            ),
            storage_budget=storage_task_budget(before, self.settings),
            pacing_seconds=max(
                self.settings.pacing_floor_seconds,
                (3_600 / quota_limit) * 1.05,
            ),
        )

    def _seed_etfs_if_ready(
        self,
        *,
        window: _RunWindow,
        before: HistoricalBackfillSnapshot,
        budget: _RunBudget,
        last_request_started_at: float,
    ) -> tuple[HistoricalBackfillSnapshot, float]:
        ready = (
            before.common_remaining == 0
            and before.etf_task_count == 0
            and budget.request_budget > 0
            and budget.storage_budget > 0
        )
        if not ready or not self._paced_wait(
            last_request_at=last_request_started_at,
            pacing_seconds=budget.pacing_seconds,
            deadline=window.deadline,
        ):
            return before, last_request_started_at

        last_request_started_at = self._monotonic()
        etf_payload = self.provider.fetch("securities")
        budget.request_budget -= 1
        _ = self.repository.seed_etfs(
            finmind_etf_schedule_rows(etf_payload),
            start_date=window.start_date,
            end_date=window.end_date,
            selection_snapshot_at=window.selection_snapshot_at,
        )
        return (
            self.repository.snapshot(
                start_date=window.start_date,
                end_date=window.end_date,
            ),
            last_request_started_at,
        )

    def _process_claimed_tasks(
        self,
        *,
        window: _RunWindow,
        max_tasks: int,
        worker_id: str,
        budget: _RunBudget,
        last_request_started_at: float,
    ) -> tuple[_RunCounters, _StopFlags]:
        counters = _RunCounters()
        stops = _StopFlags(capacity=budget.storage_budget <= 0)
        run_budget = min(max_tasks, budget.request_budget, budget.storage_budget)
        while counters.attempted < run_budget:
            if not self._paced_wait(
                last_request_at=last_request_started_at,
                pacing_seconds=budget.pacing_seconds,
                deadline=window.deadline,
            ):
                stops.time = True
                break
            claim_token = uuid4()
            task = self.repository.claim_one(
                worker_id=worker_id,
                claim_token=claim_token,
                lease_seconds=self.settings.lease_seconds,
            )
            if task is None:
                break
            counters.attempted += 1
            last_request_started_at = self._monotonic()
            if not self._process_task(task, claim_token, counters):
                stops.quota = True
                break
            if self._capacity_reached(window, counters.attempted):
                stops.capacity = True
                break
        return counters, stops

    def _process_task(
        self,
        task: HistoricalBackfillTask,
        claim_token: UUID,
        counters: _RunCounters,
    ) -> bool:
        try:
            result = self.landing_service.land_symbol(
                symbol=task.symbol,
                start_date=task.start_date,
                end_date=task.end_date,
                scheduled_market=task.market,
                asset_type=task.asset_type,
                backfill_task_id=task.task_id,
            )
            self.repository.complete(
                task=task,
                claim_token=claim_token,
                success=True,
                latest_trade_date=result.latest_trade_date,
                fetched_rows=result.fetched_rows,
                landed_rows=result.landed_rows,
                quarantined_rows=result.quarantined_rows,
                quarantine_issues=result.quarantine_issues,
                retry_after_seconds=self.settings.retry_after_seconds,
            )
            counters.record_success(result)
            return True
        except (IngestionError, ProviderError) as error:
            self.repository.complete(
                task=task,
                claim_token=claim_token,
                success=False,
                retry_after_seconds=self.settings.retry_after_seconds,
                error_code=getattr(error, "reason_code", "HISTORICAL_IMPORT_ERROR"),
            )
            counters.retried += 1
            if is_quota_error(error):
                return False
            if isinstance(error, (ProviderConfigurationError, ProviderCredentialError)):
                raise
            return True

    def _capacity_reached(self, window: _RunWindow, attempted: int) -> bool:
        # R2 capacity is bounded by object count, not Postgres relation size.
        # Avoid synchronized, storage-heavy snapshot RPCs from all credential
        # workers; they can exceed the database statement timeout even after
        # every claimed task has already completed successfully.
        if attempted % 10 != 0 or self.settings.storage_target == "R2":
            return False
        checkpoint = self.repository.snapshot(
            start_date=window.start_date,
            end_date=window.end_date,
        )
        return storage_task_budget(checkpoint, self.settings) <= 0

    def _quota_wait_summary(
        self,
        window: _RunWindow,
        before: HistoricalBackfillSnapshot,
    ) -> HistoricalBackfillSummary:
        return HistoricalBackfillSummary(
            outcome="QUOTA_WAIT",
            start_date=window.start_date.isoformat(),
            end_date=window.end_date.isoformat(),
            attempted_tasks=0,
            succeeded_tasks=0,
            retried_tasks=0,
            fetched_rows=0,
            landed_rows=0,
            quarantined_rows=0,
            quota_remaining_at_start=0,
            request_budget=0,
            storage_task_budget=storage_task_budget(before, self.settings),
            database_bytes_before=before.database_bytes,
            database_bytes_after=before.database_bytes,
            remaining_twse_common=before.twse_common_remaining,
            remaining_tpex_common=before.tpex_common_remaining,
            remaining_etf=before.etf_remaining,
            exhausted_tasks=before.exhausted,
            reason_codes=(
                "REQUEST_UNIVERSE_NOT_POINT_IN_TIME",
                "RAW_LANDING_ONLY",
                "FINMIND_QUOTA_WAIT",
            ),
        )

    @staticmethod
    def _outcome(
        *,
        counters: _RunCounters,
        stops: _StopFlags,
        budget: _RunBudget,
        after: HistoricalBackfillSnapshot,
    ) -> str:
        remaining = (
            after.twse_common_remaining
            + after.tpex_common_remaining
            + after.etf_remaining
        )
        if counters.succeeded:
            return "PROGRESSED"
        if stops.quota or budget.request_budget <= 0:
            return "QUOTA_WAIT"
        if stops.capacity:
            return "CAPACITY_GUARD"
        if stops.time:
            return "TIME_BUDGET"
        if remaining == 0:
            return "COMPLETE"
        return "NO_ELIGIBLE_TASKS"

    @staticmethod
    def _summary(
        *,
        window: _RunWindow,
        before: HistoricalBackfillSnapshot,
        after: HistoricalBackfillSnapshot,
        budget: _RunBudget,
        counters: _RunCounters,
        outcome: str,
    ) -> HistoricalBackfillSummary:
        return HistoricalBackfillSummary(
            outcome=outcome,
            start_date=window.start_date.isoformat(),
            end_date=window.end_date.isoformat(),
            attempted_tasks=counters.attempted,
            succeeded_tasks=counters.succeeded,
            retried_tasks=counters.retried,
            fetched_rows=counters.fetched_rows,
            landed_rows=counters.landed_rows,
            quarantined_rows=counters.quarantined_rows,
            quota_remaining_at_start=max(budget.quota_limit - budget.quota_used, 0),
            request_budget=budget.request_budget,
            storage_task_budget=budget.storage_budget,
            database_bytes_before=before.database_bytes,
            database_bytes_after=after.database_bytes,
            remaining_twse_common=after.twse_common_remaining,
            remaining_tpex_common=after.tpex_common_remaining,
            remaining_etf=after.etf_remaining,
            exhausted_tasks=after.exhausted,
            reason_codes=(
                "REQUEST_UNIVERSE_NOT_POINT_IN_TIME",
                "HISTORICAL_VINTAGE_UNAVAILABLE",
                "RAW_LANDING_ONLY",
                outcome,
            ),
        )
