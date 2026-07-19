"""Quota-aware runner for TWSE adjusted, institutional, and margin history."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
from time import monotonic, sleep
from typing import Protocol, final
from uuid import uuid4

from src.data.providers.contracts import ProviderPayload
from src.data.providers.errors import ProviderError, ProviderHttpError

from .contracts import IngestionError
from .historical_backfill_runtime import finmind_quota_counters, is_quota_error
from .historical_backfill_settings import HistoricalBackfillSettings
from .historical_daily_bar_import_contracts import HistoricalSymbolLandingResult
from .historical_supplemental_backfill_contracts import (
    HistoricalSupplementalBackfillSummary,
)
from .historical_supplemental_backfill_repository import (
    HistoricalSupplementalBackfillRepository,
)


class SupplementalQuotaProvider(Protocol):
    def fetch_quota(self) -> ProviderPayload: ...


class SupplementalLandingService(Protocol):
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


@final
class HistoricalSupplementalBackfillCoordinator:
    def __init__(
        self,
        *,
        provider: SupplementalQuotaProvider,
        repository: HistoricalSupplementalBackfillRepository,
        landing_service: SupplementalLandingService,
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

    def _wait(self, *, last_request_at: float, seconds: float, deadline: float) -> bool:
        wait = max(seconds - (self._monotonic() - last_request_at), 0)
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
    ) -> HistoricalSupplementalBackfillSummary:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if not 1 <= max_tasks <= 100:
            raise ValueError("max_tasks must be between 1 and 100")
        if not worker_id.strip() or len(worker_id) > 128:
            raise ValueError("worker_id must contain 1 to 128 characters")
        if self.settings.storage_target != "R2":
            raise ValueError("supplemental history must be archived to R2")

        started_at = self._monotonic()
        deadline = started_at + self.settings.max_runtime_seconds
        observed_at = self._now()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("now_fn must return a timezone-aware datetime")
        self.repository.ensure_finmind_source()
        if self.settings.seed_common_tasks:
            _ = self.repository.seed_twse(
                start_date=start_date,
                end_date=end_date,
                selection_snapshot_at=observed_at,
            )
        before = self.repository.snapshot(start_date=start_date, end_date=end_date)
        last_request_at = self._monotonic()
        try:
            quota_payload = self.provider.fetch_quota()
        except ProviderHttpError as error:
            if not is_quota_error(error):
                raise
            return self._summary(
                outcome="QUOTA_WAIT",
                start_date=start_date,
                end_date=end_date,
                snapshot=before,
                quota_remaining=0,
                request_budget=0,
                reason_codes=("FINMIND_QUOTA_WAIT",),
            )
        quota_used, quota_limit = finmind_quota_counters(quota_payload)
        quota_remaining = max(quota_limit - quota_used, 0)
        request_budget = max(quota_remaining - self.settings.quota_reserve, 0)
        run_budget = min(
            max_tasks,
            request_budget,
            self.settings.max_archive_objects_per_run,
        )
        pacing_seconds = max(
            self.settings.pacing_floor_seconds,
            (3_600 / quota_limit) * 1.05,
        )
        attempted = succeeded = retried = 0
        fetched = archived = quarantined = 0
        reason_codes = {
            "REQUEST_UNIVERSE_NOT_POINT_IN_TIME",
            "HISTORICAL_VINTAGE_UNAVAILABLE",
            "IDENTITY_UNRESOLVED",
            "RAW_LANDING_ONLY",
        }
        while attempted < run_budget:
            if not self._wait(
                last_request_at=last_request_at,
                seconds=pacing_seconds,
                deadline=deadline,
            ):
                reason_codes.add("RUNTIME_BUDGET_REACHED")
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
            last_request_at = self._monotonic()
            try:
                result = self.landing_service.land_symbol(
                    dataset=task.source_dataset,
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
                succeeded += 1
                fetched += result.fetched_rows
                archived += result.landed_rows
                quarantined += result.quarantined_rows
            except (IngestionError, ProviderError) as error:
                self.repository.complete(
                    task=task,
                    claim_token=claim_token,
                    success=False,
                    retry_after_seconds=self.settings.retry_after_seconds,
                    error_code=getattr(
                        error, "reason_code", "HISTORICAL_SUPPLEMENTAL_IMPORT_ERROR"
                    ),
                )
                retried += 1
                if is_quota_error(error):
                    reason_codes.add("FINMIND_QUOTA_WAIT")
                    break
        after = self.repository.snapshot(start_date=start_date, end_date=end_date)
        outcome = "COMPLETED" if after.remaining == 0 else "PARTIAL"
        return HistoricalSupplementalBackfillSummary(
            outcome=outcome,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            attempted_tasks=attempted,
            succeeded_tasks=succeeded,
            retried_tasks=retried,
            fetched_rows=fetched,
            archived_rows=archived,
            quarantined_rows=quarantined,
            quota_remaining_at_start=quota_remaining,
            request_budget=request_budget,
            remaining_adjusted_bars=after.adjusted_bars_remaining,
            remaining_institutional_flows=after.institutional_flows_remaining,
            remaining_margin_short=after.margin_short_remaining,
            exhausted_tasks=after.exhausted,
            reason_codes=tuple(sorted(reason_codes)),
        )

    @staticmethod
    def _summary(
        *,
        outcome: str,
        start_date: date,
        end_date: date,
        snapshot: object,
        quota_remaining: int,
        request_budget: int,
        reason_codes: tuple[str, ...],
    ) -> HistoricalSupplementalBackfillSummary:
        from .historical_supplemental_backfill_contracts import (
            HistoricalSupplementalBackfillSnapshot,
        )

        if not isinstance(snapshot, HistoricalSupplementalBackfillSnapshot):
            raise TypeError("snapshot has an invalid type")
        return HistoricalSupplementalBackfillSummary(
            outcome=outcome,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            attempted_tasks=0,
            succeeded_tasks=0,
            retried_tasks=0,
            fetched_rows=0,
            archived_rows=0,
            quarantined_rows=0,
            quota_remaining_at_start=quota_remaining,
            request_budget=request_budget,
            remaining_adjusted_bars=snapshot.adjusted_bars_remaining,
            remaining_institutional_flows=snapshot.institutional_flows_remaining,
            remaining_margin_short=snapshot.margin_short_remaining,
            exhausted_tasks=snapshot.exhausted,
            reason_codes=reason_codes,
        )
