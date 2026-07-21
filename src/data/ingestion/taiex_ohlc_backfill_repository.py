"""Supabase adapter for the isolated official TAIEX monthly OHLC queue."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Protocol, cast, final
from uuid import UUID

from .contracts import IngestionError
from .historical_backfill_contracts import HistoricalBackfillTask
from .normalizers import data_source_rows
from .taiex_ohlc_backfill_contracts import TaiexOhlcQueueSnapshot


class TaiexOhlcQueueWriter(Protocol):
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
class TaiexOhlcBackfillRepository:
    def __init__(self, writer: TaiexOhlcQueueWriter) -> None:
        self.writer = writer

    def ensure_twse_source(self) -> None:
        source = next(
            row for row in data_source_rows() if row["source_code"] == "TWSE"
        )
        returned = self.writer.upsert(
            "data_sources",
            [source],
            on_conflict="source_code",
            preserve_existing=True,
        )
        if returned:
            raise AssertionError("source upsert should not request returned rows")

    def seed(
        self,
        *,
        start_month: date,
        end_month: date,
        selection_snapshot_at: datetime,
    ) -> int:
        value = self.writer.rpc(
            "seed_taiex_price_index_ohlc_tasks",
            {
                "p_start_month": start_month.isoformat(),
                "p_end_month": end_month.isoformat(),
                "p_selection_snapshot_at": selection_snapshot_at.isoformat(),
            },
        )
        if isinstance(value, bool) or not isinstance(value, int):
            raise IngestionError(
                "TAIEX_OHLC_BACKFILL_RPC_INVALID",
                "TAIEX OHLC task seeding returned an invalid result",
            )
        return value

    def claim(
        self,
        *,
        worker_id: str,
        claim_token: UUID,
        lease_seconds: int,
    ) -> HistoricalBackfillTask | None:
        raw = self.writer.rpc(
            "claim_taiex_price_index_ohlc_task",
            {
                "p_worker_id": worker_id,
                "p_claim_token": str(claim_token),
                "p_lease_seconds": lease_seconds,
            },
        )
        if not isinstance(raw, list):
            raise IngestionError(
                "TAIEX_OHLC_BACKFILL_RPC_INVALID",
                "TAIEX OHLC task claim returned an invalid result",
            )
        rows = cast(list[object], raw)
        if len(rows) > 1 or any(not isinstance(row, Mapping) for row in rows):
            raise IngestionError(
                "TAIEX_OHLC_BACKFILL_RPC_INVALID",
                "TAIEX OHLC task claim returned an invalid row collection",
            )
        return (
            HistoricalBackfillTask.from_row(cast(Mapping[str, object], rows[0]))
            if rows
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
        archived_rows: int = 0,
        retry_after_seconds: int = 900,
        error_code: str | None = None,
    ) -> None:
        value = self.writer.rpc(
            "complete_taiex_price_index_ohlc_task",
            {
                "p_task_id": task.task_id,
                "p_claim_token": str(claim_token),
                "p_success": success,
                "p_latest_completed_trade_date": latest_trade_date,
                "p_fetched_rows": fetched_rows,
                "p_archived_rows": archived_rows,
                "p_retry_after_seconds": retry_after_seconds,
                "p_error_code": error_code,
            },
        )
        if value is not True:
            raise IngestionError(
                "TAIEX_OHLC_BACKFILL_LEASE_LOST",
                "TAIEX OHLC task completion was rejected",
            )

    def snapshot(
        self,
        *,
        start_month: date,
        end_month: date,
    ) -> TaiexOhlcQueueSnapshot:
        raw = self.writer.rpc(
            "taiex_price_index_ohlc_backfill_snapshot",
            {
                "p_start_month": start_month.isoformat(),
                "p_end_month": end_month.isoformat(),
            },
        )
        if not isinstance(raw, list):
            raise IngestionError(
                "TAIEX_OHLC_BACKFILL_RPC_INVALID",
                "TAIEX OHLC snapshot returned an invalid result",
            )
        rows = cast(list[object], raw)
        if len(rows) != 1 or not isinstance(rows[0], Mapping):
            raise IngestionError(
                "TAIEX_OHLC_BACKFILL_RPC_INVALID",
                "TAIEX OHLC snapshot did not return exactly one row",
            )
        return TaiexOhlcQueueSnapshot.from_row(
            cast(Mapping[str, object], rows[0])
        )
