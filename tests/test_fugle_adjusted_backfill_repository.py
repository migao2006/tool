from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from typing import final
from uuid import uuid4

from src.data.ingestion.historical_fugle_adjusted_backfill_repository import (
    FugleAdjustedBackfillRepository,
)


START = date(2024, 1, 1)
END = date(2025, 1, 1)


@final
class FakeWriter:
    def __init__(self, rpc_results: Mapping[str, object]) -> None:
        self.rpc_results = dict(rpc_results)
        self.rpc_calls: list[tuple[str, Mapping[str, object]]] = []
        self.upserts: list[Sequence[Mapping[str, object]]] = []

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
        _ = (table, on_conflict, select, return_rows, preserve_existing)
        self.upserts.append(rows)
        return []

    def rpc(self, function_name: str, parameters: Mapping[str, object]) -> object:
        self.rpc_calls.append((function_name, parameters))
        return self.rpc_results[function_name]


def test_repository_uses_only_dedicated_fugle_rpcs_and_source() -> None:
    writer = FakeWriter(
        {
            "historical_fugle_adjusted_backfill_snapshot": [
                {
                    "task_count": 0,
                    "remaining": 0,
                    "succeeded": 0,
                    "exhausted": 0,
                    "archive_object_count": 0,
                    "archive_row_count": 0,
                    "archive_byte_count": 0,
                }
            ],
            "seed_historical_fugle_adjusted_twse_tasks": 1,
            "claim_historical_fugle_adjusted_backfill_task": [],
        }
    )
    repository = FugleAdjustedBackfillRepository(writer)

    repository.ensure_fugle_source()
    assert (
        repository.seed_twse(
            start_date=START,
            end_date=END,
            selection_snapshot_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        )
        == 1
    )
    assert (
        repository.claim_one(
            worker_id="worker",
            claim_token=uuid4(),
            lease_seconds=1_800,
        )
        is None
    )
    _ = repository.snapshot(start_date=START, end_date=END)

    assert writer.upserts[0][0]["source_code"] == "FUGLE"
    names = [name for name, _ in writer.rpc_calls]
    assert names == [
        "seed_historical_fugle_adjusted_twse_tasks",
        "claim_historical_fugle_adjusted_backfill_task",
        "historical_fugle_adjusted_backfill_snapshot",
    ]
    assert not any("supplemental" in name for name in names)
