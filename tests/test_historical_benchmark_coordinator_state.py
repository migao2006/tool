from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.historical_backfill_contracts import HistoricalBackfillTask
from src.data.ingestion.historical_benchmark_contracts import (
    HistoricalBenchmarkBackfillState,
)
from src.data.ingestion.historical_benchmark_coordinator import (
    HistoricalBenchmarkBackfillCoordinator,
)


START = date(2021, 7, 19)
END = date(2026, 7, 17)
NOW = datetime(2026, 7, 19, tzinfo=timezone.utc)


class _Repository:
    def __init__(self, state: HistoricalBenchmarkBackfillState) -> None:
        self.state = state

    def ensure_finmind_source(self) -> None:
        pass

    def seed(self, **_: object) -> int:
        return 1

    def claim(self, **_: object) -> HistoricalBackfillTask | None:
        return None

    def backfill_state(self, **_: object) -> HistoricalBenchmarkBackfillState:
        return self.state

    def complete(
        self,
        *,
        task: HistoricalBackfillTask,
        claim_token: UUID,
        success: bool,
        **_: object,
    ) -> None:
        _ = (task, claim_token, success)
        raise AssertionError("no task is claimed in state tests")


class _Landing:
    def land(self, **_: object) -> object:
        raise AssertionError("state-only outcomes must not call the provider")


def _run(state: HistoricalBenchmarkBackfillState):
    return HistoricalBenchmarkBackfillCoordinator(
        repository=_Repository(state),
        landing_service=_Landing(),  # type: ignore[arg-type]
        now_fn=lambda: NOW,
    ).run(start_date=START, end_date=END, worker_id="benchmark-state-test")


@pytest.mark.parametrize(
    ("task_status", "outcome"),
    (
        ("LEASED", "TASK_LEASED"),
        ("PENDING", "TASK_DEFERRED"),
        ("RETRY", "TASK_DEFERRED"),
    ),
)
def test_reports_non_claimable_queue_state(
    task_status: str,
    outcome: str,
) -> None:
    summary = _run(
        HistoricalBenchmarkBackfillState(
            archive_exists=False,
            task_id=17,
            task_status=task_status,
            last_error_code=None,
        )
    )

    assert summary.outcome == outcome
    assert summary.queue_status == task_status
    assert f"BENCHMARK_TASK_{task_status}" in summary.reason_codes


@pytest.mark.parametrize(
    ("state", "reason_code"),
    (
        (
            HistoricalBenchmarkBackfillState(False, 17, "EXHAUSTED", "FAILED"),
            "HISTORICAL_BENCHMARK_TASK_EXHAUSTED",
        ),
        (
            HistoricalBenchmarkBackfillState(False, None, None, None),
            "HISTORICAL_BENCHMARK_TASK_MISSING",
        ),
        (
            HistoricalBenchmarkBackfillState(False, 17, "SUCCEEDED", None),
            "HISTORICAL_BENCHMARK_ARCHIVE_MISSING",
        ),
        (
            HistoricalBenchmarkBackfillState(True, 17, "RETRY", "FAILED"),
            "HISTORICAL_BENCHMARK_STATE_INCONSISTENT",
        ),
    ),
)
def test_fails_closed_for_invalid_terminal_state(
    state: HistoricalBenchmarkBackfillState,
    reason_code: str,
) -> None:
    with pytest.raises(IngestionError) as captured:
        _ = _run(state)

    assert captured.value.reason_code == reason_code
