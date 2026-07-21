"""Isolated Supabase queue adapter for Fugle adjusted TWSE history."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Protocol, cast, final
from uuid import UUID

from .contracts import IngestionError
from .historical_backfill_contracts import HistoricalBackfillTask
from .historical_fugle_adjusted_backfill_contracts import (
    FugleAdjustedBackfillSnapshot,
)
from .source_catalog import fugle_data_source_row


class FugleQueueWriter(Protocol):
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


def _one_row(raw: object) -> Mapping[str, object]:
    if not isinstance(raw, list):
        raise IngestionError(
            "FUGLE_ADJUSTED_RPC_INVALID",
            "Fugle adjusted RPC returned an invalid result",
        )
    rows = cast(list[object], raw)
    if len(rows) != 1 or not isinstance(rows[0], Mapping):
        raise IngestionError(
            "FUGLE_ADJUSTED_RPC_INVALID",
            "Fugle adjusted RPC returned an invalid row collection",
        )
    return cast(Mapping[str, object], rows[0])


@final
class FugleAdjustedBackfillRepository:
    """Use only FUGLE/adjusted_bars RPCs; never share FinMind claims."""

    def __init__(self, writer: FugleQueueWriter) -> None:
        self.writer = writer

    def ensure_contract_available(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> FugleAdjustedBackfillSnapshot:
        """Fail before source seeding or R2 access when migration is absent."""

        return self.snapshot(start_date=start_date, end_date=end_date)

    def ensure_fugle_source(self) -> None:
        returned = self.writer.upsert(
            "data_sources",
            [fugle_data_source_row()],
            on_conflict="source_code",
            preserve_existing=True,
        )
        if returned:
            raise AssertionError("source upsert should not request returned rows")

    def seed_twse(
        self,
        *,
        start_date: date,
        end_date: date,
        selection_snapshot_at: datetime,
    ) -> int:
        value = self.writer.rpc(
            "seed_historical_fugle_adjusted_twse_tasks",
            {
                "p_start_date": start_date.isoformat(),
                "p_end_date": end_date.isoformat(),
                "p_selection_snapshot_at": selection_snapshot_at.isoformat(),
            },
        )
        if isinstance(value, bool) or not isinstance(value, int):
            raise IngestionError(
                "FUGLE_ADJUSTED_RPC_INVALID",
                "Fugle adjusted task seeding returned an invalid result",
            )
        return value

    def claim_one(
        self,
        *,
        worker_id: str,
        claim_token: UUID,
        lease_seconds: int,
    ) -> HistoricalBackfillTask | None:
        raw = self.writer.rpc(
            "claim_historical_fugle_adjusted_backfill_task",
            {
                "p_worker_id": worker_id,
                "p_claim_token": str(claim_token),
                "p_lease_seconds": lease_seconds,
            },
        )
        if not isinstance(raw, list):
            raise IngestionError(
                "FUGLE_ADJUSTED_RPC_INVALID",
                "Fugle adjusted task claim returned an invalid result",
            )
        rows = cast(list[object], raw)
        if len(rows) > 1 or any(not isinstance(row, Mapping) for row in rows):
            raise IngestionError(
                "FUGLE_ADJUSTED_RPC_INVALID",
                "Fugle adjusted task claim returned an invalid row collection",
            )
        if not rows:
            return None
        task = HistoricalBackfillTask.from_row(cast(Mapping[str, object], rows[0]))
        if (
            task.source_dataset != "adjusted_bars"
            or task.market != "TWSE"
            or task.asset_type != "COMMON_STOCK"
            or (task.end_date - task.start_date).days + 1 > 366
        ):
            raise IngestionError(
                "FUGLE_ADJUSTED_TASK_SCOPE_INVALID",
                "The dedicated Fugle RPC returned an out-of-scope task",
            )
        return task

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
                "Fugle adjusted completion was rejected after its lease expired",
            )

    def snapshot(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> FugleAdjustedBackfillSnapshot:
        raw = self.writer.rpc(
            "historical_fugle_adjusted_backfill_snapshot",
            {
                "p_start_date": start_date.isoformat(),
                "p_end_date": end_date.isoformat(),
            },
        )
        return FugleAdjustedBackfillSnapshot.from_row(_one_row(raw))
