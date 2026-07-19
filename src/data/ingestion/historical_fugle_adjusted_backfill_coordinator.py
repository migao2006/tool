"""Bounded, pacing-aware coordinator for Fugle adjusted TWSE archives."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
from time import monotonic, sleep
from typing import Protocol, final
from uuid import UUID, uuid4

from src.data.providers.errors import ProviderError, ProviderHttpError

from .contracts import IngestionError
from .historical_backfill_settings import HistoricalBackfillSettings
from .historical_backfill_contracts import HistoricalBackfillTask
from .historical_daily_bar_import_contracts import HistoricalSymbolLandingResult
from .historical_fugle_adjusted_backfill_contracts import (
    FugleAdjustedBackfillSettings,
    FugleAdjustedBackfillSnapshot,
    FugleAdjustedBackfillSummary,
)


class FugleAdjustedLandingService(Protocol):
    def land_symbol(
        self,
        *,
        dataset: str,
        symbol: str,
        start_date: date,
        end_date: date,
        scheduled_market: str,
        asset_type: str,
        backfill_task_id: int | None,
    ) -> HistoricalSymbolLandingResult: ...


class FugleAdjustedQueue(Protocol):
    def ensure_contract_available(
        self, *, start_date: date, end_date: date
    ) -> FugleAdjustedBackfillSnapshot: ...

    def ensure_fugle_source(self) -> None: ...

    def seed_twse(
        self,
        *,
        start_date: date,
        end_date: date,
        selection_snapshot_at: datetime,
    ) -> int: ...

    def claim_one(
        self, *, worker_id: str, claim_token: UUID, lease_seconds: int
    ) -> HistoricalBackfillTask | None: ...

    def complete(
        self,
        *,
        task: HistoricalBackfillTask,
        claim_token: UUID,
        success: bool,
        retry_after_seconds: int,
        latest_trade_date: str | None = None,
        fetched_rows: int = 0,
        landed_rows: int = 0,
        quarantined_rows: int = 0,
        quarantine_issues: int = 0,
        error_code: str | None = None,
    ) -> None: ...

    def snapshot(
        self, *, start_date: date, end_date: date
    ) -> FugleAdjustedBackfillSnapshot: ...


@final
class FugleAdjustedBackfillCoordinator:
    def __init__(
        self,
        *,
        repository: FugleAdjustedQueue,
        landing_service: FugleAdjustedLandingService,
        runtime_settings: HistoricalBackfillSettings,
        fugle_settings: FugleAdjustedBackfillSettings,
        sleep_fn: Callable[[float], None] = sleep,
        monotonic_fn: Callable[[], float] = monotonic,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.landing_service = landing_service
        self.runtime_settings = runtime_settings
        self.fugle_settings = fugle_settings
        self._sleep = sleep_fn
        self._monotonic = monotonic_fn
        self._now = now_fn or (lambda: datetime.now(timezone.utc))

    def _wait_for_pacing(
        self,
        *,
        last_request_at: float | None,
        deadline: float,
    ) -> bool:
        if last_request_at is None:
            return self._monotonic() < deadline
        elapsed = self._monotonic() - last_request_at
        wait = max(self.fugle_settings.pacing_seconds - elapsed, 0.0)
        if self._monotonic() + wait >= deadline:
            return False
        if wait:
            self._sleep(wait)
        return True

    def run(
        self,
        *,
        start_date: date,
        end_date: date,
        max_tasks: int,
        worker_id: str,
    ) -> FugleAdjustedBackfillSummary:
        if not self.fugle_settings.enabled:
            raise IngestionError(
                "FUGLE_ADJUSTED_BACKFILL_DISABLED",
                "Fugle adjusted backfill is disabled by default",
            )
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if not 1 <= max_tasks <= 100:
            raise ValueError("max_tasks must be between 1 and 100")
        if not worker_id.strip() or len(worker_id) > 128:
            raise ValueError("worker_id must contain 1 to 128 characters")
        if self.runtime_settings.storage_target != "R2":
            raise ValueError("Fugle adjusted history must be archived to R2")

        # This dedicated RPC is introduced by the migration. Calling it before
        # any source seed or archive action makes an undeployed migration fail closed.
        _ = self.repository.ensure_contract_available(
            start_date=start_date,
            end_date=end_date,
        )
        observed_at = self._now()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("now_fn must return a timezone-aware datetime")
        self.repository.ensure_fugle_source()
        if self.runtime_settings.seed_common_tasks:
            _ = self.repository.seed_twse(
                start_date=start_date,
                end_date=end_date,
                selection_snapshot_at=observed_at,
            )

        request_budget = min(
            max_tasks,
            self.fugle_settings.request_budget_per_run,
            self.runtime_settings.max_archive_objects_per_run,
        )
        deadline = self._monotonic() + self.runtime_settings.max_runtime_seconds
        last_request_at: float | None = None
        attempted = succeeded = retried = 0
        fetched = archived = quarantined = 0
        rate_limited = False
        reason_codes = {
            "FUGLE_CONFIGURED_REQUEST_BUDGET",
            "REQUEST_UNIVERSE_NOT_POINT_IN_TIME",
            "HISTORICAL_VINTAGE_UNAVAILABLE",
            "IDENTITY_UNRESOLVED",
            "RAW_LANDING_ONLY",
        }

        while attempted < request_budget:
            claim_token = uuid4()
            task = self.repository.claim_one(
                worker_id=worker_id,
                claim_token=claim_token,
                lease_seconds=self.runtime_settings.lease_seconds,
            )
            if task is None:
                break
            if not self._wait_for_pacing(
                last_request_at=last_request_at,
                deadline=deadline,
            ):
                self.repository.complete(
                    task=task,
                    claim_token=claim_token,
                    success=False,
                    retry_after_seconds=self.fugle_settings.retry_after_seconds,
                    error_code="FUGLE_RUNTIME_BUDGET_REACHED",
                )
                reason_codes.add("RUNTIME_BUDGET_REACHED")
                break

            attempted += 1
            last_request_at = self._monotonic()
            try:
                result = self.landing_service.land_symbol(
                    dataset="adjusted_bars",
                    symbol=task.symbol,
                    start_date=task.start_date,
                    end_date=task.end_date,
                    scheduled_market="TWSE",
                    asset_type="COMMON_STOCK",
                    backfill_task_id=task.task_id,
                )
                self.repository.complete(
                    task=task,
                    claim_token=claim_token,
                    success=True,
                    retry_after_seconds=self.fugle_settings.retry_after_seconds,
                    latest_trade_date=result.latest_trade_date,
                    fetched_rows=result.fetched_rows,
                    landed_rows=result.landed_rows,
                    quarantined_rows=result.quarantined_rows,
                    quarantine_issues=result.quarantine_issues,
                )
                succeeded += 1
                fetched += result.fetched_rows
                archived += result.landed_rows
                quarantined += result.quarantined_rows
            except (IngestionError, ProviderError) as error:
                is_rate_limit = (
                    isinstance(error, ProviderHttpError) and error.status_code == 429
                )
                error_code = (
                    "FUGLE_RATE_LIMITED"
                    if is_rate_limit
                    else getattr(error, "reason_code", "FUGLE_ADJUSTED_IMPORT_ERROR")
                )
                self.repository.complete(
                    task=task,
                    claim_token=claim_token,
                    success=False,
                    retry_after_seconds=self.fugle_settings.retry_after_seconds,
                    error_code=error_code,
                )
                retried += 1
                if is_rate_limit:
                    rate_limited = True
                    reason_codes.add("FUGLE_RATE_LIMIT_WAIT")
                    break

        after = self.repository.snapshot(start_date=start_date, end_date=end_date)
        if after.exhausted > 0:
            outcome = "EXHAUSTED_TASKS"
            reason_codes.add("FUGLE_ADJUSTED_TASKS_EXHAUSTED")
        elif rate_limited:
            outcome = "RATE_LIMIT_WAIT"
        else:
            outcome = "COMPLETED" if after.remaining == 0 else "PARTIAL"
        return self._summary(
            outcome=outcome,
            start_date=start_date,
            end_date=end_date,
            attempted=attempted,
            succeeded=succeeded,
            retried=retried,
            fetched=fetched,
            archived=archived,
            quarantined=quarantined,
            request_budget=request_budget,
            snapshot=after,
            reason_codes=tuple(sorted(reason_codes)),
        )

    def _summary(
        self,
        *,
        outcome: str,
        start_date: date,
        end_date: date,
        attempted: int,
        succeeded: int,
        retried: int,
        fetched: int,
        archived: int,
        quarantined: int,
        request_budget: int,
        snapshot: FugleAdjustedBackfillSnapshot,
        reason_codes: tuple[str, ...],
    ) -> FugleAdjustedBackfillSummary:
        return FugleAdjustedBackfillSummary(
            outcome=outcome,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            attempted_tasks=attempted,
            succeeded_tasks=succeeded,
            retried_tasks=retried,
            fetched_rows=fetched,
            archived_rows=archived,
            quarantined_rows=quarantined,
            configured_request_budget=request_budget,
            pacing_seconds=self.fugle_settings.pacing_seconds,
            remaining_tasks=snapshot.remaining,
            exhausted_tasks=snapshot.exhausted,
            archive_object_count=snapshot.archive_object_count,
            archive_row_count=snapshot.archive_row_count,
            archive_byte_count=snapshot.archive_byte_count,
            reason_codes=reason_codes,
        )
