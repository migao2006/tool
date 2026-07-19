from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from uuid import UUID

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.taiex_ohlc_backfill_repository import (
    TaiexOhlcBackfillRepository,
)


class FakeWriter:
    def __init__(self) -> None:
        self.upserts: list[dict[str, object]] = []
        self.rpcs: list[tuple[str, dict[str, object]]] = []
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
        self.upserts.append(
            {
                "table": table,
                "rows": [dict(row) for row in rows],
                "on_conflict": on_conflict,
                "select": select,
                "return_rows": return_rows,
                "preserve_existing": preserve_existing,
            }
        )
        return []

    def rpc(self, function_name: str, parameters: Mapping[str, object]) -> object:
        self.rpcs.append((function_name, dict(parameters)))
        return self.responses.get(function_name)


def _task_row() -> dict[str, object]:
    return {
        "task_id": 19,
        "source_dataset": "taiex_price_index_ohlc",
        "source_symbol": "TAIEX",
        "display_name": "TAIEX Price Index OHLC",
        "market": "TWSE",
        "asset_type": "BENCHMARK",
        "priority": 10,
        "requested_start_date": "2024-01-01",
        "requested_end_date": "2024-01-31",
        "attempt_count": 1,
        "max_attempts": 5,
    }


def _snapshot_row() -> dict[str, object]:
    return {
        "task_count": 3,
        "pending": 1,
        "leased": 0,
        "retry": 0,
        "succeeded": 2,
        "exhausted": 0,
        "archive_object_count": 2,
        "archive_row_count": 42,
        "archive_byte_count": 4096,
    }


def test_repository_uses_only_the_isolated_taiex_rpcs() -> None:
    writer = FakeWriter()
    writer.responses.update(
        {
            "seed_taiex_price_index_ohlc_tasks": 3,
            "claim_taiex_price_index_ohlc_task": [_task_row()],
            "complete_taiex_price_index_ohlc_task": True,
            "taiex_price_index_ohlc_backfill_snapshot": [_snapshot_row()],
        }
    )
    repository = TaiexOhlcBackfillRepository(writer)
    snapshot_at = datetime(2026, 7, 19, 1, tzinfo=timezone.utc)
    token = UUID("11111111-1111-4111-8111-111111111111")

    repository.ensure_twse_source()
    inserted = repository.seed(
        start_month=date(2024, 1, 1),
        end_month=date(2024, 3, 1),
        selection_snapshot_at=snapshot_at,
    )
    task = repository.claim(
        worker_id="taiex-worker",
        claim_token=token,
        lease_seconds=600,
    )
    assert task is not None
    repository.complete(
        task=task,
        claim_token=token,
        success=True,
        latest_trade_date="2024-01-31",
        fetched_rows=21,
        archived_rows=21,
    )
    snapshot = repository.snapshot(
        start_month=date(2024, 1, 1),
        end_month=date(2024, 3, 1),
    )

    assert inserted == 3
    assert writer.upserts[0]["table"] == "data_sources"
    source_rows = writer.upserts[0]["rows"]
    assert isinstance(source_rows, list)
    assert isinstance(source_rows[0], dict)
    assert source_rows[0]["source_code"] == "TWSE"
    assert writer.upserts[0]["preserve_existing"] is True
    assert [name for name, _ in writer.rpcs] == [
        "seed_taiex_price_index_ohlc_tasks",
        "claim_taiex_price_index_ohlc_task",
        "complete_taiex_price_index_ohlc_task",
        "taiex_price_index_ohlc_backfill_snapshot",
    ]
    assert writer.rpcs[0][1] == {
        "p_start_month": "2024-01-01",
        "p_end_month": "2024-03-01",
        "p_selection_snapshot_at": snapshot_at.isoformat(),
    }
    assert writer.rpcs[1][1]["p_claim_token"] == str(token)
    assert writer.rpcs[2][1]["p_task_id"] == 19
    assert snapshot.archive_row_count == 42
    assert snapshot.remaining == 1


@pytest.mark.parametrize(
    ("function_name", "response", "operation"),
    [
        ("seed_taiex_price_index_ohlc_tasks", True, "seed"),
        ("claim_taiex_price_index_ohlc_task", {}, "claim"),
        ("complete_taiex_price_index_ohlc_task", False, "complete"),
        ("taiex_price_index_ohlc_backfill_snapshot", [], "snapshot"),
    ],
)
def test_repository_fails_closed_on_invalid_rpc_shapes(
    function_name: str,
    response: object,
    operation: str,
) -> None:
    writer = FakeWriter()
    writer.responses[function_name] = response
    repository = TaiexOhlcBackfillRepository(writer)
    token = UUID("11111111-1111-4111-8111-111111111111")

    with pytest.raises(IngestionError):
        if operation == "seed":
            _ = repository.seed(
                start_month=date(2024, 1, 1),
                end_month=date(2024, 1, 1),
                selection_snapshot_at=datetime.now(timezone.utc),
            )
        elif operation == "claim":
            _ = repository.claim(
                worker_id="worker",
                claim_token=token,
                lease_seconds=600,
            )
        elif operation == "complete":
            from src.data.ingestion.historical_backfill_contracts import (
                HistoricalBackfillTask,
            )

            repository.complete(
                task=HistoricalBackfillTask.from_row(_task_row()),
                claim_token=token,
                success=True,
            )
        else:
            _ = repository.snapshot(
                start_month=date(2024, 1, 1),
                end_month=date(2024, 1, 1),
            )
