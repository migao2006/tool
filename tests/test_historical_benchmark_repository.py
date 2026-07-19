from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.historical_benchmark_repository import (
    HistoricalBenchmarkBackfillRepository,
)


START = date(2021, 7, 19)
END = date(2026, 7, 17)


class FakeWriter:
    def __init__(
        self,
        *,
        task_rows: list[dict[str, object]],
        archive_rows: list[dict[str, object]] | None = None,
    ) -> None:
        self.rows = {
            "historical_backfill_tasks": task_rows,
            "historical_archive_objects": archive_rows or [],
        }
        self.select_calls: list[dict[str, object]] = []

    def upsert(
        self,
        table: str,
        rows: Sequence[Mapping[str, object]],
        *,
        on_conflict: str,
        select: str | None = None,
        return_rows: bool = False,
        preserve_existing: bool = False,
    ) -> list[dict[str, object]]:
        _ = (
            table,
            rows,
            on_conflict,
            select,
            return_rows,
            preserve_existing,
        )
        raise AssertionError("upsert is not expected")

    def rpc(self, function_name: str, parameters: Mapping[str, object]) -> object:
        _ = (function_name, parameters)
        raise AssertionError("rpc is not expected")

    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]:
        self.select_calls.append(
            {
                "table": table,
                "select": select,
                "filters": dict(filters or {}),
                "limit": limit,
            }
        )
        return list(self.rows[table])


def test_reads_exact_fixed_range_task_and_archive_state() -> None:
    writer = FakeWriter(
        task_rows=[{"task_id": 17, "status": "SUCCEEDED", "last_error_code": None}],
        archive_rows=[{"archive_id": 101}],
    )

    state = HistoricalBenchmarkBackfillRepository(writer).backfill_state(
        start_date=START,
        end_date=END,
    )

    assert state.archive_exists is True
    assert state.task_id == 17
    assert state.task_status == "SUCCEEDED"
    assert writer.select_calls[0] == {
            "table": "historical_backfill_tasks",
            "select": "task_id,status,last_error_code",
            "filters": {
                "provider_code": "eq.FINMIND",
                "source_dataset": "eq.benchmark_total_return",
                "source_symbol": "eq.TAIEX",
                "market": "eq.TWSE",
                "asset_type": "eq.BENCHMARK",
                "requested_start_date": "eq.2021-07-19",
                "requested_end_date": "eq.2026-07-17",
            },
            "limit": 2,
        }
    assert writer.select_calls[1] == {
        "table": "historical_archive_objects",
        "select": "archive_id",
        "filters": {
            "provider_code": "eq.FINMIND",
            "source_dataset": "eq.benchmark_total_return",
            "source_symbol": "eq.TAIEX",
            "scheduled_market": "eq.TWSE",
            "asset_type": "eq.BENCHMARK",
            "requested_start_date": "eq.2021-07-19",
            "requested_end_date": "eq.2026-07-17",
        },
        "limit": 2,
    }


@pytest.mark.parametrize(
    "task_rows",
    (
        [{"task_id": 17, "status": "UNKNOWN", "last_error_code": None}],
        [
            {"task_id": 17, "status": "SUCCEEDED", "last_error_code": None},
            {"task_id": 18, "status": "EXHAUSTED", "last_error_code": "FAILED"},
        ],
    ),
)
def test_rejects_invalid_or_duplicate_task_state(
    task_rows: list[dict[str, object]],
) -> None:
    with pytest.raises(IngestionError) as captured:
        _ = HistoricalBenchmarkBackfillRepository(
            FakeWriter(task_rows=task_rows)
        ).backfill_state(
            start_date=START,
            end_date=END,
        )

    assert captured.value.reason_code == "HISTORICAL_BENCHMARK_STATE_INVALID"


def test_missing_fixed_range_task_is_explicit() -> None:
    state = HistoricalBenchmarkBackfillRepository(
        FakeWriter(task_rows=[])
    ).backfill_state(
        start_date=START,
        end_date=END,
    )

    assert state.task_status is None
    assert state.archive_exists is False
