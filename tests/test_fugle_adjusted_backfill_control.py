from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timezone
from typing import final
from uuid import UUID

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.historical_backfill_contracts import HistoricalBackfillTask
from src.data.ingestion.historical_backfill_settings import HistoricalBackfillSettings
from src.data.ingestion.historical_daily_bar_import_contracts import (
    HistoricalSymbolLandingResult,
)
from src.data.ingestion.historical_fugle_adjusted_backfill_contracts import (
    FugleAdjustedBackfillSettings,
    FugleAdjustedBackfillSnapshot,
)
from src.data.ingestion.historical_fugle_adjusted_backfill_coordinator import (
    FugleAdjustedBackfillCoordinator,
)
from src.data.providers.errors import ProviderHttpError


START = date(2024, 1, 1)
END = date(2025, 1, 1)


def _snapshot(*, remaining: int, objects: int = 0) -> FugleAdjustedBackfillSnapshot:
    return FugleAdjustedBackfillSnapshot(
        task_count=remaining + objects,
        remaining=remaining,
        succeeded=objects,
        exhausted=0,
        archive_object_count=objects,
        archive_row_count=objects * 200,
        archive_byte_count=objects * 2_000,
    )


def _task(task_id: int, symbol: str = "2330") -> HistoricalBackfillTask:
    return HistoricalBackfillTask(
        task_id=task_id,
        source_dataset="adjusted_bars",
        symbol=symbol,
        display_name=None,
        market="TWSE",
        asset_type="COMMON_STOCK",
        priority=10,
        start_date=START,
        end_date=END,
        attempt_count=1,
        max_attempts=5,
    )


@final
class FakeQueue:
    def __init__(
        self,
        tasks: Sequence[HistoricalBackfillTask],
        snapshots: Sequence[FugleAdjustedBackfillSnapshot],
    ) -> None:
        self.tasks = list(tasks)
        self.snapshots = list(snapshots)
        self.completed: list[tuple[int, bool, str | None]] = []
        self.preflight_calls = self.seed_calls = self.ensure_calls = 0

    def ensure_contract_available(
        self, *, start_date: date, end_date: date
    ) -> FugleAdjustedBackfillSnapshot:
        _ = (start_date, end_date)
        self.preflight_calls += 1
        if len(self.snapshots) > 1:
            return self.snapshots.pop(0)
        return self.snapshots[0]

    def ensure_fugle_source(self) -> None:
        self.ensure_calls += 1

    def seed_twse(
        self,
        *,
        start_date: date,
        end_date: date,
        selection_snapshot_at: datetime,
    ) -> int:
        _ = (start_date, end_date, selection_snapshot_at)
        self.seed_calls += 1
        return len(self.tasks)

    def claim_one(
        self, *, worker_id: str, claim_token: UUID, lease_seconds: int
    ) -> HistoricalBackfillTask | None:
        _ = (worker_id, claim_token, lease_seconds)
        return self.tasks.pop(0) if self.tasks else None

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
    ) -> None:
        _ = (
            claim_token,
            retry_after_seconds,
            latest_trade_date,
            fetched_rows,
            landed_rows,
            quarantined_rows,
            quarantine_issues,
        )
        self.completed.append((task.task_id, success, error_code))

    def snapshot(
        self, *, start_date: date, end_date: date
    ) -> FugleAdjustedBackfillSnapshot:
        _ = (start_date, end_date)
        if len(self.snapshots) > 1:
            return self.snapshots.pop(0)
        return self.snapshots[0]


@final
class FakeLanding:
    def __init__(self, *, rate_limit_symbol: str | None = None) -> None:
        self.rate_limit_symbol = rate_limit_symbol
        self.calls: list[tuple[str, str]] = []

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
    ) -> HistoricalSymbolLandingResult:
        _ = (start_date, end_date, backfill_task_id)
        self.calls.append((dataset, symbol))
        assert scheduled_market == "TWSE"
        assert asset_type == "COMMON_STOCK"
        if symbol == self.rate_limit_symbol:
            raise ProviderHttpError(429, "https://api.fugle.tw/safe")
        return HistoricalSymbolLandingResult(
            symbol=symbol,
            fetched_rows=200,
            landed_rows=200,
            quarantined_rows=0,
            quarantine_issues=0,
            latest_trade_date="2024-12-31",
            source_payload_hash="0" * 64,
        )


@final
class Clock:
    def __init__(self) -> None:
        self.value = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


def _coordinator(
    queue: FakeQueue,
    landing: FakeLanding,
    *,
    enabled: bool = True,
    budget: int = 2,
    clock: Clock | None = None,
) -> FugleAdjustedBackfillCoordinator:
    active_clock = clock or Clock()
    return FugleAdjustedBackfillCoordinator(
        repository=queue,
        landing_service=landing,
        runtime_settings=HistoricalBackfillSettings(
            storage_target="R2",
            max_runtime_seconds=60,
            max_archive_objects_per_run=100,
        ),
        fugle_settings=FugleAdjustedBackfillSettings(
            enabled=enabled,
            request_budget_per_run=budget,
            pacing_seconds=2.0,
            retry_after_seconds=3_600,
        ),
        sleep_fn=active_clock.sleep,
        monotonic_fn=active_clock.monotonic,
        now_fn=lambda: datetime(2026, 7, 19, tzinfo=timezone.utc),
    )


def test_feature_flag_fails_before_queue_or_provider_actions() -> None:
    queue = FakeQueue([], [_snapshot(remaining=0)])

    with pytest.raises(IngestionError) as captured:
        _ = _coordinator(queue, FakeLanding(), enabled=False).run(
            start_date=START,
            end_date=END,
            max_tasks=1,
            worker_id="worker",
        )

    assert captured.value.reason_code == "FUGLE_ADJUSTED_BACKFILL_DISABLED"
    assert queue.preflight_calls == 0
    assert queue.ensure_calls == 0


def test_budget_and_pacing_bound_requests_and_keep_research_status() -> None:
    clock = Clock()
    queue = FakeQueue(
        [_task(1, "2330"), _task(2, "2317"), _task(3, "2303")],
        [_snapshot(remaining=3), _snapshot(remaining=1, objects=2)],
    )
    landing = FakeLanding()

    summary = _coordinator(queue, landing, budget=2, clock=clock).run(
        start_date=START,
        end_date=END,
        max_tasks=100,
        worker_id="worker",
    )

    assert landing.calls == [("adjusted_bars", "2330"), ("adjusted_bars", "2317")]
    assert clock.sleeps == [2.0]
    assert summary.attempted_tasks == 2
    assert summary.configured_request_budget == 2
    assert summary.system_status == "RESEARCH_ONLY"
    assert summary.usage_scope == "RAW_LANDING_ONLY"
    assert summary.outcome == "PARTIAL"
    assert queue.preflight_calls == 1
    assert queue.ensure_calls == 1
    assert queue.seed_calls == 1


def test_http_429_stops_run_and_returns_task_to_retry() -> None:
    queue = FakeQueue(
        [_task(1, "2330"), _task(2, "2317")],
        [_snapshot(remaining=2), _snapshot(remaining=2)],
    )

    summary = _coordinator(
        queue,
        FakeLanding(rate_limit_symbol="2330"),
        budget=2,
    ).run(
        start_date=START,
        end_date=END,
        max_tasks=2,
        worker_id="worker",
    )

    assert summary.outcome == "RATE_LIMIT_WAIT"
    assert summary.attempted_tasks == 1
    assert "FUGLE_RATE_LIMIT_WAIT" in summary.reason_codes
    assert queue.completed == [(1, False, "FUGLE_RATE_LIMITED")]
