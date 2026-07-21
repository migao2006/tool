"""Service-role repository for the resumable historical backfill queue."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Protocol, cast, final
from uuid import UUID

from .contracts import IngestionError
from .historical_backfill_contracts import (
    HistoricalBackfillSnapshot,
    HistoricalBackfillTask,
)
from .source_catalog import finmind_data_source_row


class BackfillQueueWriter(Protocol):
    def upsert(
        self,
        table: str,
        rows: Sequence[Mapping[str, object]],
        *,
        on_conflict: str,
        select: str | None = None,
        return_rows: bool = False,
        preserve_existing: bool = False,
    ) -> list[dict[str, object]]: ...

    def rpc(self, function_name: str, parameters: Mapping[str, object]) -> object: ...


@final
class HistoricalBackfillRepository:
    def __init__(self, writer: BackfillQueueWriter) -> None:
        self.writer = writer

    def ensure_finmind_source(self) -> None:
        rows = self.writer.upsert(
            "data_sources",
            [finmind_data_source_row()],
            on_conflict="source_code",
            preserve_existing=True,
        )
        if rows:
            raise AssertionError("source upsert should not request returned rows")

    def seed_common(
        self, *, start_date: date, end_date: date, selection_snapshot_at: datetime
    ) -> int:
        value = self.writer.rpc(
            "seed_historical_backfill_common_tasks",
            {
                "p_start_date": start_date.isoformat(),
                "p_end_date": end_date.isoformat(),
                "p_selection_snapshot_at": selection_snapshot_at.isoformat(),
            },
        )
        if isinstance(value, bool) or not isinstance(value, int):
            raise IngestionError(
                "HISTORICAL_BACKFILL_RPC_INVALID",
                "Common-task seeding returned an invalid result",
            )
        return value

    def seed_delisted_common(
        self, *, start_date: date, end_date: date, selection_snapshot_at: datetime
    ) -> int:
        """Schedule unresolved official delistings without guessing a security ID."""

        value = self.writer.rpc(
            "seed_historical_backfill_delisted_common_tasks",
            {
                "p_start_date": start_date.isoformat(),
                "p_end_date": end_date.isoformat(),
                "p_selection_snapshot_at": selection_snapshot_at.isoformat(),
            },
        )
        if isinstance(value, bool) or not isinstance(value, int):
            raise IngestionError(
                "HISTORICAL_BACKFILL_RPC_INVALID",
                "Delisted common-task seeding returned an invalid result",
            )
        return value

    def seed_etfs(
        self,
        rows: Sequence[Mapping[str, object]],
        *,
        start_date: date,
        end_date: date,
        selection_snapshot_at: datetime,
    ) -> int:
        tasks = [
            {
                "provider_code": "FINMIND",
                "source_dataset": "daily_bars",
                "source_symbol": row["source_symbol"],
                "display_name": row.get("display_name"),
                "market": row["market"],
                "asset_type": "ETF",
                "requested_start_date": start_date.isoformat(),
                "requested_end_date": end_date.isoformat(),
                "selection_snapshot_at": selection_snapshot_at.isoformat(),
            }
            for row in rows
        ]
        returned = self.writer.upsert(
            "historical_backfill_tasks",
            tasks,
            on_conflict=(
                "provider_code,source_dataset,market,source_symbol,"
                "requested_start_date,requested_end_date"
            ),
            select="task_id",
            return_rows=True,
            preserve_existing=True,
        )
        return len(returned)

    def claim_one(
        self, *, worker_id: str, claim_token: UUID, lease_seconds: int
    ) -> HistoricalBackfillTask | None:
        raw = self.writer.rpc(
            "claim_historical_backfill_tasks",
            {
                "p_provider_code": "FINMIND",
                "p_worker_id": worker_id,
                "p_claim_token": str(claim_token),
                "p_limit": 1,
                "p_lease_seconds": lease_seconds,
            },
        )
        if not isinstance(raw, list):
            raise IngestionError(
                "HISTORICAL_BACKFILL_RPC_INVALID",
                "Task claim returned an invalid row collection",
            )
        raw_rows = cast(list[object], raw)
        rows = [
            cast(Mapping[str, object], row)
            for row in raw_rows
            if isinstance(row, Mapping)
        ]
        if len(rows) > 1 or len(rows) != len(raw_rows):
            raise IngestionError(
                "HISTORICAL_BACKFILL_RPC_INVALID",
                "Task claim returned an invalid number of rows",
            )
        return HistoricalBackfillTask.from_row(rows[0]) if rows else None

    def complete(
        self,
        *,
        task: HistoricalBackfillTask,
        claim_token: UUID,
        success: bool,
        latest_trade_date: str | None = None,
        fetched_rows: int = 0,
        landed_rows: int = 0,
        quarantined_rows: int = 0,
        quarantine_issues: int = 0,
        retry_after_seconds: int,
        error_code: str | None = None,
    ) -> None:
        value = self.writer.rpc(
            "complete_historical_backfill_task",
            {
                "p_task_id": task.task_id,
                "p_claim_token": str(claim_token),
                "p_success": success,
                "p_latest_completed_trade_date": latest_trade_date,
                "p_fetched_rows": fetched_rows,
                "p_landed_rows": landed_rows,
                "p_quarantined_rows": quarantined_rows,
                "p_quarantine_issues": quarantine_issues,
                "p_retry_after_seconds": retry_after_seconds,
                "p_error_code": error_code,
            },
        )
        if value is not True:
            raise IngestionError(
                "HISTORICAL_BACKFILL_LEASE_LOST",
                "Task completion was rejected because its lease is no longer valid",
            )

    def snapshot(
        self, *, start_date: date, end_date: date
    ) -> HistoricalBackfillSnapshot:
        raw = self.writer.rpc(
            "historical_backfill_snapshot",
            {
                "p_start_date": start_date.isoformat(),
                "p_end_date": end_date.isoformat(),
            },
        )
        if not isinstance(raw, list):
            raise IngestionError(
                "HISTORICAL_BACKFILL_RPC_INVALID",
                "Backfill snapshot returned an invalid result",
            )
        raw_rows = cast(list[object], raw)
        if len(raw_rows) != 1 or not isinstance(raw_rows[0], Mapping):
            raise IngestionError(
                "HISTORICAL_BACKFILL_RPC_INVALID",
                "Backfill snapshot returned an invalid result",
            )
        return HistoricalBackfillSnapshot.from_row(
            cast(Mapping[str, object], raw_rows[0])
        )
