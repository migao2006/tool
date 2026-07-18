"""Quota-, time-, and capacity-aware coordinator for historical landing data."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
from time import monotonic, sleep
from typing import final
from uuid import uuid4

from src.data.providers.errors import (
    ProviderConfigurationError,
    ProviderCredentialError,
    ProviderError,
    ProviderHttpError,
)

from .contracts import IngestionError
from .historical_backfill_contracts import HistoricalBackfillSummary
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
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if not 1 <= max_tasks <= 100:
            raise ValueError("max_tasks must be between 1 and 100")
        if not worker_id.strip() or len(worker_id) > 128:
            raise ValueError("worker_id must contain 1 to 128 characters")

        started_at = self._monotonic()
        deadline = started_at + self.settings.max_runtime_seconds
        selection_snapshot_at = self._now()
        if selection_snapshot_at.tzinfo is None:
            raise ValueError("now_fn must return a timezone-aware datetime")

        self.repository.ensure_finmind_source()
        _ = self.repository.seed_common(
            start_date=start_date,
            end_date=end_date,
            selection_snapshot_at=selection_snapshot_at,
        )
        before = self.repository.snapshot(start_date=start_date, end_date=end_date)
        # Pace logical FinMind calls from request start to request start. Transport
        # retries remain internal to the HTTP client and are not counted as separate
        # logical calls by this coordinator.
        last_request_started_at = self._monotonic()
        try:
            quota_payload = self.provider.fetch_quota()
        except ProviderHttpError as error:
            if not is_quota_error(error):
                raise
            return HistoricalBackfillSummary(
                outcome="QUOTA_WAIT",
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
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
        quota_used, quota_limit = finmind_quota_counters(quota_payload)
        request_budget = max(quota_limit - quota_used - self.settings.quota_reserve, 0)
        storage_budget = storage_task_budget(before, self.settings)
        pacing_seconds = max(
            self.settings.pacing_floor_seconds,
            (3_600 / quota_limit) * 1.05,
        )

        if (
            before.common_remaining == 0
            and before.etf_task_count == 0
            and request_budget > 0
            and storage_budget > 0
        ):
            if self._paced_wait(
                last_request_at=last_request_started_at,
                pacing_seconds=pacing_seconds,
                deadline=deadline,
            ):
                last_request_started_at = self._monotonic()
                etf_payload = self.provider.fetch("securities")
                request_budget -= 1
                _ = self.repository.seed_etfs(
                    finmind_etf_schedule_rows(etf_payload),
                    start_date=start_date,
                    end_date=end_date,
                    selection_snapshot_at=selection_snapshot_at,
                )
                before = self.repository.snapshot(
                    start_date=start_date, end_date=end_date
                )

        run_budget = min(max_tasks, request_budget, storage_budget)
        attempted = succeeded = retried = 0
        fetched_rows = landed_rows = quarantined_rows = 0
        stopped_for_quota = False
        stopped_for_time = False
        stopped_for_capacity = storage_budget <= 0

        while attempted < run_budget:
            if not self._paced_wait(
                last_request_at=last_request_started_at,
                pacing_seconds=pacing_seconds,
                deadline=deadline,
            ):
                stopped_for_time = True
                break
            claim_token = uuid4()
            task = self.repository.claim_one(
                worker_id=worker_id,
                claim_token=claim_token,
                lease_seconds=self.settings.lease_seconds,
            )
            if task is None:
                break
            attempted += 1
            last_request_started_at = self._monotonic()
            try:
                result = self.landing_service.land_symbol(
                    symbol=task.symbol,
                    start_date=task.start_date,
                    end_date=task.end_date,
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
                succeeded += 1
                fetched_rows += result.fetched_rows
                landed_rows += result.landed_rows
                quarantined_rows += result.quarantined_rows
            except (IngestionError, ProviderError) as error:
                self.repository.complete(
                    task=task,
                    claim_token=claim_token,
                    success=False,
                    retry_after_seconds=self.settings.retry_after_seconds,
                    error_code=getattr(error, "reason_code", "HISTORICAL_IMPORT_ERROR"),
                )
                retried += 1
                if is_quota_error(error):
                    stopped_for_quota = True
                    break
                if isinstance(
                    error, (ProviderConfigurationError, ProviderCredentialError)
                ):
                    raise
            if attempted % 10 == 0:
                checkpoint = self.repository.snapshot(
                    start_date=start_date, end_date=end_date
                )
                if storage_task_budget(checkpoint, self.settings) <= 0:
                    stopped_for_capacity = True
                    break

        if succeeded:
            self.landing_service.refresh_home_status()
        after = self.repository.snapshot(start_date=start_date, end_date=end_date)
        remaining = (
            after.twse_common_remaining
            + after.tpex_common_remaining
            + after.etf_remaining
        )
        if succeeded:
            outcome = "PROGRESSED"
        elif stopped_for_quota or request_budget <= 0:
            outcome = "QUOTA_WAIT"
        elif stopped_for_capacity:
            outcome = "CAPACITY_GUARD"
        elif stopped_for_time:
            outcome = "TIME_BUDGET"
        elif remaining == 0:
            outcome = "COMPLETE"
        else:
            outcome = "NO_ELIGIBLE_TASKS"
        return HistoricalBackfillSummary(
            outcome=outcome,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            attempted_tasks=attempted,
            succeeded_tasks=succeeded,
            retried_tasks=retried,
            fetched_rows=fetched_rows,
            landed_rows=landed_rows,
            quarantined_rows=quarantined_rows,
            quota_remaining_at_start=max(quota_limit - quota_used, 0),
            request_budget=request_budget,
            storage_task_budget=storage_budget,
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
