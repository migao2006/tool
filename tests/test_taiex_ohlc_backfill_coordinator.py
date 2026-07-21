from __future__ import annotations

from datetime import date, datetime, timezone
from typing import final
from uuid import UUID

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.historical_backfill_contracts import HistoricalBackfillTask
from src.data.ingestion.taiex_ohlc_backfill_contracts import (
    TaiexOhlcLandingResult,
    TaiexOhlcQueueSnapshot,
)
from src.data.ingestion.taiex_ohlc_backfill_coordinator import (
    TaiexOhlcBackfillCoordinator,
)


def _task(month: int, *, dataset: str = "taiex_price_index_ohlc") -> HistoricalBackfillTask:
    ends = {1: 31, 2: 29, 3: 31}
    return HistoricalBackfillTask(
        task_id=month,
        source_dataset=dataset,
        symbol="TAIEX",
        display_name="TAIEX Price Index OHLC",
        market="TWSE",
        asset_type="BENCHMARK",
        priority=10,
        start_date=date(2024, month, 1),
        end_date=date(2024, month, ends[month]),
        attempt_count=1,
        max_attempts=5,
    )


def _snapshot(*, remaining: int = 0, exhausted: int = 0) -> TaiexOhlcQueueSnapshot:
    return TaiexOhlcQueueSnapshot(
        task_count=2 + exhausted,
        pending=remaining,
        leased=0,
        retry=0,
        succeeded=2,
        exhausted=exhausted,
        archive_object_count=2,
        archive_row_count=42,
        archive_byte_count=2048,
    )


@final
class FakeRepository:
    def __init__(
        self,
        tasks: list[HistoricalBackfillTask],
        *,
        snapshot: TaiexOhlcQueueSnapshot | None = None,
    ) -> None:
        self.tasks = list(tasks)
        self.current_snapshot = snapshot or _snapshot()
        self.source_calls = 0
        self.seed_calls: list[dict[str, object]] = []
        self.claim_tokens: list[UUID] = []
        self.complete_calls: list[dict[str, object]] = []

    def ensure_twse_source(self) -> None:
        self.source_calls += 1

    def seed(self, **kwargs: object) -> int:
        self.seed_calls.append(kwargs)
        return len(self.tasks)

    def claim(
        self,
        *,
        worker_id: str,
        claim_token: UUID,
        lease_seconds: int,
    ) -> HistoricalBackfillTask | None:
        assert worker_id == "worker"
        assert lease_seconds == 600
        self.claim_tokens.append(claim_token)
        return self.tasks.pop(0) if self.tasks else None

    def complete(self, **kwargs: object) -> None:
        self.complete_calls.append(kwargs)

    def snapshot(
        self,
        *,
        start_month: date,
        end_month: date,
    ) -> TaiexOhlcQueueSnapshot:
        assert start_month == date(2024, 1, 1)
        assert end_month == date(2024, 2, 1)
        return self.current_snapshot


@final
class FakeLanding:
    def __init__(self, *, failure: IngestionError | None = None) -> None:
        self.failure = failure
        self.months: list[date] = []

    def land(
        self,
        *,
        month: date,
        backfill_task_id: int,
    ) -> TaiexOhlcLandingResult:
        self.months.append(month)
        if self.failure is not None:
            raise self.failure
        return TaiexOhlcLandingResult(
            fetched_rows=21,
            archived_rows=21,
            latest_trade_date=month.replace(day=20).isoformat(),
            source_payload_hash="a" * 64,
            object_key=f"twse/taiex/{backfill_task_id}.parquet",
            object_created=backfill_task_id == 1,
            byte_size=1024,
        )


def _coordinator(
    repository: FakeRepository,
    landing: FakeLanding,
    sleeps: list[float],
) -> TaiexOhlcBackfillCoordinator:
    return TaiexOhlcBackfillCoordinator(
        repository=repository,
        landing_service=landing,
        now_fn=lambda: datetime(2026, 7, 19, tzinfo=timezone.utc),
        sleep_fn=sleeps.append,
    )


def test_bounded_run_processes_months_sequentially_and_preserves_semantics() -> None:
    repository = FakeRepository([_task(1), _task(2)])
    landing = FakeLanding()
    sleeps: list[float] = []

    summary = _coordinator(repository, landing, sleeps).run(
        start_month=date(2024, 1, 1),
        end_month=date(2024, 2, 1),
        worker_id="worker",
        max_tasks=2,
        request_interval_seconds=0.5,
        lease_seconds=600,
    )

    assert landing.months == [date(2024, 1, 1), date(2024, 2, 1)]
    assert sleeps == [0.5]
    assert len(set(repository.claim_tokens)) == 2
    assert [call["success"] for call in repository.complete_calls] == [True, True]
    assert summary.outcome == "COMPLETE"
    assert summary.attempted_tasks == summary.succeeded_tasks == 2
    assert summary.fetched_rows == summary.archived_rows == 42
    assert summary.created_objects == summary.reused_objects == 1
    assert summary.benchmark_semantics == "PRICE_INDEX_NOT_TOTAL_RETURN"
    assert summary.usage_scope == "RAW_LANDING_ONLY"
    assert summary.system_status == "RESEARCH_ONLY"


def test_invalid_dataset_is_rejected_and_marked_for_retry() -> None:
    repository = FakeRepository([_task(1, dataset="benchmark_total_return")])

    with pytest.raises(IngestionError) as captured:
        _ = _coordinator(repository, FakeLanding(), []).run(
            start_month=date(2024, 1, 1),
            end_month=date(2024, 2, 1),
            worker_id="worker",
            max_tasks=1,
            request_interval_seconds=0.5,
            lease_seconds=600,
        )

    assert captured.value.reason_code == "TAIEX_OHLC_BACKFILL_TASK_SCOPE_INVALID"
    assert repository.complete_calls[0]["success"] is False
    assert (
        repository.complete_calls[0]["error_code"]
        == "TAIEX_OHLC_BACKFILL_TASK_SCOPE_INVALID"
    )


def test_ingestion_failure_releases_task_to_retry_and_propagates() -> None:
    repository = FakeRepository([_task(1)])
    failure = IngestionError("TAIEX_OHLC_PROVIDER_CONTRACT_FAILED", "bad payload")

    with pytest.raises(IngestionError) as captured:
        _ = _coordinator(repository, FakeLanding(failure=failure), []).run(
            start_month=date(2024, 1, 1),
            end_month=date(2024, 2, 1),
            worker_id="worker",
            max_tasks=1,
            request_interval_seconds=0.5,
            lease_seconds=600,
        )

    assert captured.value is failure
    assert repository.complete_calls[0]["success"] is False
    assert (
        repository.complete_calls[0]["error_code"]
        == "TAIEX_OHLC_PROVIDER_CONTRACT_FAILED"
    )


@pytest.mark.parametrize(
    ("end_month", "max_tasks", "interval"),
    [
        (date(2026, 7, 1), 1, 0.5),
        (date(2024, 2, 1), 25, 0.5),
        (date(2024, 2, 1), 1, 0.1),
    ],
)
def test_run_rejects_incomplete_month_or_unsafe_budget(
    end_month: date,
    max_tasks: int,
    interval: float,
) -> None:
    repository = FakeRepository([])

    with pytest.raises(ValueError):
        _ = _coordinator(repository, FakeLanding(), []).run(
            start_month=date(2024, 1, 1),
            end_month=end_month,
            worker_id="worker",
            max_tasks=max_tasks,
            request_interval_seconds=interval,
            lease_seconds=600,
        )

    assert repository.source_calls == 0


def test_exhausted_queue_is_blocked_even_when_nothing_is_claimed() -> None:
    repository = FakeRepository([], snapshot=_snapshot(exhausted=1))

    summary = _coordinator(repository, FakeLanding(), []).run(
        start_month=date(2024, 1, 1),
        end_month=date(2024, 2, 1),
        worker_id="worker",
        max_tasks=1,
        request_interval_seconds=0.5,
        lease_seconds=600,
    )

    assert summary.outcome == "BLOCKED"
