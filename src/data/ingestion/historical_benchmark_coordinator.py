"""Coordinate one idempotent TAIEX benchmark archive request."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Protocol, final
from uuid import UUID, uuid4

from src.data.providers.errors import ProviderError

from .contracts import IngestionError
from .historical_backfill_contracts import HistoricalBackfillTask
from .historical_benchmark_contracts import (
    BENCHMARK_DATASET,
    BENCHMARK_DATA_ID,
    BENCHMARK_REASON_CODES,
    HistoricalBenchmarkBackfillState,
    HistoricalBenchmarkBackfillSummary,
    HistoricalBenchmarkLandingResult,
)


class HistoricalBenchmarkRepository(Protocol):
    def ensure_finmind_source(self) -> None: ...

    def seed(
        self,
        *,
        start_date: date,
        end_date: date,
        selection_snapshot_at: datetime,
    ) -> int: ...

    def claim(
        self, *, worker_id: str, claim_token: UUID, lease_seconds: int
    ) -> HistoricalBackfillTask | None: ...

    def backfill_state(
        self, *, start_date: date, end_date: date
    ) -> HistoricalBenchmarkBackfillState: ...

    def complete(
        self,
        *,
        task: HistoricalBackfillTask,
        claim_token: UUID,
        success: bool,
        latest_trade_date: str | None = None,
        fetched_rows: int = 0,
        archived_rows: int = 0,
        quarantined_rows: int = 0,
        quarantine_issues: int = 0,
        error_code: str | None = None,
    ) -> None: ...


class HistoricalBenchmarkLanding(Protocol):
    def land(
        self,
        *,
        start_date: date,
        end_date: date,
        backfill_task_id: int,
    ) -> HistoricalBenchmarkLandingResult: ...


@final
class HistoricalBenchmarkBackfillCoordinator:
    def __init__(
        self,
        *,
        repository: HistoricalBenchmarkRepository,
        landing_service: HistoricalBenchmarkLanding,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.landing_service = landing_service
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        *,
        start_date: date,
        end_date: date,
        worker_id: str,
    ) -> HistoricalBenchmarkBackfillSummary:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        now = self.now_fn()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now_fn must return a timezone-aware datetime")
        self.repository.ensure_finmind_source()
        _ = self.repository.seed(
            start_date=start_date,
            end_date=end_date,
            selection_snapshot_at=now,
        )
        claim_token = uuid4()
        task = self.repository.claim(
            worker_id=worker_id,
            claim_token=claim_token,
            lease_seconds=1800,
        )
        if task is None:
            state = self.repository.backfill_state(
                start_date=start_date,
                end_date=end_date,
            )
            task_status = state.task_status
            if task_status == "EXHAUSTED":
                raise IngestionError(
                    "HISTORICAL_BENCHMARK_TASK_EXHAUSTED",
                    "benchmark task exhausted its retry budget",
                )
            if task_status is None:
                raise IngestionError(
                    "HISTORICAL_BENCHMARK_TASK_MISSING",
                    "benchmark task is missing after queue seeding",
                )
            if task_status == "SUCCEEDED" and not state.archive_exists:
                raise IngestionError(
                    "HISTORICAL_BENCHMARK_ARCHIVE_MISSING",
                    "succeeded benchmark task has no exact archive manifest",
                )
            if state.archive_exists and task_status != "SUCCEEDED":
                raise IngestionError(
                    "HISTORICAL_BENCHMARK_STATE_INCONSISTENT",
                    "benchmark archive and queue state are inconsistent",
                )
            outcome = {
                "SUCCEEDED": "ALREADY_ARCHIVED",
                "LEASED": "TASK_LEASED",
                "PENDING": "TASK_DEFERRED",
                "RETRY": "TASK_DEFERRED",
            }[task_status]
            return HistoricalBenchmarkBackfillSummary(
                outcome=outcome,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                task_id=state.task_id,
                request_count=0,
                fetched_rows=0,
                archived_rows=0,
                quarantined_rows=0,
                object_key=None,
                source_payload_hash=None,
                reason_codes=(
                    *BENCHMARK_REASON_CODES,
                    f"BENCHMARK_TASK_{task_status}",
                ),
                queue_status=task_status,
                last_error_code=state.last_error_code,
            )
        if (
            task.source_dataset != BENCHMARK_DATASET
            or task.symbol != BENCHMARK_DATA_ID
            or task.market != "TWSE"
            or task.asset_type != "BENCHMARK"
            or task.start_date != start_date
            or task.end_date != end_date
        ):
            self.repository.complete(
                task=task,
                claim_token=claim_token,
                success=False,
                error_code="HISTORICAL_BENCHMARK_TASK_SCOPE_INVALID",
            )
            raise IngestionError(
                "HISTORICAL_BENCHMARK_TASK_SCOPE_INVALID",
                "claimed task does not match the fixed TAIEX benchmark request",
            )
        try:
            landed = self.landing_service.land(
                start_date=start_date,
                end_date=end_date,
                backfill_task_id=task.task_id,
            )
        except (IngestionError, ProviderError) as error:
            self.repository.complete(
                task=task,
                claim_token=claim_token,
                success=False,
                error_code=getattr(error, "reason_code", "BENCHMARK_FETCH_FAILED"),
            )
            raise
        self.repository.complete(
            task=task,
            claim_token=claim_token,
            success=True,
            latest_trade_date=landed.latest_trade_date,
            fetched_rows=landed.fetched_rows,
            archived_rows=landed.archived_rows,
            quarantined_rows=landed.quarantined_rows,
            quarantine_issues=landed.quarantine_issues,
        )
        return HistoricalBenchmarkBackfillSummary(
            outcome="ARCHIVED",
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            task_id=task.task_id,
            request_count=1,
            fetched_rows=landed.fetched_rows,
            archived_rows=landed.archived_rows,
            quarantined_rows=landed.quarantined_rows,
            object_key=landed.object_key,
            source_payload_hash=landed.source_payload_hash,
        )
