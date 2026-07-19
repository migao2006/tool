"""Supabase queue metadata adapter for TWSE supplemental history."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Protocol, cast, final
from uuid import UUID

from .contracts import IngestionError
from .historical_backfill_contracts import HistoricalBackfillTask
from .historical_supplemental_backfill_contracts import (
    HistoricalSupplementalBackfillSnapshot,
)
from .source_catalog import finmind_data_source_row


class SupplementalQueueWriter(Protocol):
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
class HistoricalSupplementalBackfillRepository:
    def __init__(self, writer: SupplementalQueueWriter) -> None:
        self.writer = writer

    def ensure_finmind_source(self) -> None:
        returned = self.writer.upsert(
            "data_sources",
            [finmind_data_source_row()],
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
            "seed_historical_supplemental_twse_tasks",
            {
                "p_start_date": start_date.isoformat(),
                "p_end_date": end_date.isoformat(),
                "p_selection_snapshot_at": selection_snapshot_at.isoformat(),
            },
        )
        if isinstance(value, bool) or not isinstance(value, int):
            raise IngestionError(
                "HISTORICAL_SUPPLEMENTAL_RPC_INVALID",
                "supplemental task seeding returned an invalid result",
            )
        return value

    def claim_one(
        self, *, worker_id: str, claim_token: UUID, lease_seconds: int
    ) -> HistoricalBackfillTask | None:
        raw = self.writer.rpc(
            "claim_historical_supplemental_backfill_task",
            {
                "p_provider_code": "FINMIND",
                "p_worker_id": worker_id,
                "p_claim_token": str(claim_token),
                "p_lease_seconds": lease_seconds,
            },
        )
        if not isinstance(raw, list):
            raise IngestionError(
                "HISTORICAL_SUPPLEMENTAL_RPC_INVALID",
                "supplemental task claim returned an invalid result",
            )
        raw_rows = cast(list[object], raw)
        if len(raw_rows) > 1 or any(not isinstance(row, Mapping) for row in raw_rows):
            raise IngestionError(
                "HISTORICAL_SUPPLEMENTAL_RPC_INVALID",
                "supplemental task claim returned an invalid row collection",
            )
        return (
            HistoricalBackfillTask.from_row(cast(Mapping[str, object], raw_rows[0]))
            if raw_rows
            else None
        )

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
                "supplemental completion was rejected after its lease expired",
            )

    def snapshot(
        self, *, start_date: date, end_date: date
    ) -> HistoricalSupplementalBackfillSnapshot:
        raw = self.writer.rpc(
            "historical_supplemental_backfill_snapshot",
            {
                "p_start_date": start_date.isoformat(),
                "p_end_date": end_date.isoformat(),
            },
        )
        if not isinstance(raw, list):
            raise IngestionError(
                "HISTORICAL_SUPPLEMENTAL_RPC_INVALID",
                "supplemental snapshot returned an invalid result",
            )
        raw_rows = cast(list[object], raw)
        if len(raw_rows) != 1 or not isinstance(raw_rows[0], Mapping):
            raise IngestionError(
                "HISTORICAL_SUPPLEMENTAL_RPC_INVALID",
                "supplemental snapshot returned an invalid result",
            )
        return HistoricalSupplementalBackfillSnapshot.from_row(
            cast(Mapping[str, object], raw_rows[0])
        )
