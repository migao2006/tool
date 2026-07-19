from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from uuid import UUID

from src.data.ingestion.historical_supplemental_backfill_repository import (
    HistoricalSupplementalBackfillRepository,
)


class FakeWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.responses: dict[str, object] = {}

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
        return []

    def rpc(self, function_name: str, parameters: Mapping[str, object]) -> object:
        self.calls.append((function_name, dict(parameters)))
        return self.responses[function_name]


def _task_row() -> dict[str, object]:
    return {
        "task_id": 9,
        "source_dataset": "adjusted_bars",
        "source_symbol": "2330",
        "display_name": "台積電",
        "market": "TWSE",
        "asset_type": "COMMON_STOCK",
        "priority": 10,
        "requested_start_date": "2021-07-19",
        "requested_end_date": "2026-07-17",
        "attempt_count": 1,
        "max_attempts": 5,
    }


def test_repository_preserves_dataset_when_claiming_shared_queue() -> None:
    writer = FakeWriter()
    writer.responses["claim_historical_supplemental_backfill_task"] = [_task_row()]
    repository = HistoricalSupplementalBackfillRepository(writer)

    task = repository.claim_one(
        worker_id="worker",
        claim_token=UUID("11111111-1111-1111-1111-111111111111"),
        lease_seconds=1800,
    )

    assert task is not None
    assert task.source_dataset == "adjusted_bars"
    assert writer.calls[0][0] == "claim_historical_supplemental_backfill_task"


def test_seed_and_snapshot_use_dataset_specific_rpc_contracts() -> None:
    writer = FakeWriter()
    writer.responses["seed_historical_supplemental_twse_tasks"] = 2700
    writer.responses["historical_supplemental_backfill_snapshot"] = [
        {
            "task_count": 2700,
            "adjusted_bars_remaining": 900,
            "institutional_flows_remaining": 900,
            "margin_short_remaining": 900,
            "succeeded": 0,
            "exhausted": 0,
        }
    ]
    repository = HistoricalSupplementalBackfillRepository(writer)

    inserted = repository.seed_twse(
        start_date=date(2021, 7, 19),
        end_date=date(2026, 7, 17),
        selection_snapshot_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )
    snapshot = repository.snapshot(
        start_date=date(2021, 7, 19),
        end_date=date(2026, 7, 17),
    )

    assert inserted == 2700
    assert snapshot.remaining == 2700
    assert [name for name, _ in writer.calls] == [
        "seed_historical_supplemental_twse_tasks",
        "historical_supplemental_backfill_snapshot",
    ]
