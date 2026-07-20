"""Fetch, normalize, and archive one completed TPEx calendar month."""

from __future__ import annotations

from datetime import date
from typing import Protocol, final

from src.data.providers.contracts import ProviderPayload

from .historical_daily_bar_archive_service import HistoricalArchiveWriteResult
from .tpex_ohlc_backfill_contracts import TpexOhlcLandingResult
from .tpex_ohlc_contracts import NormalizedTpexOhlcBatch
from .tpex_ohlc_normalizer import normalize_tpex_monthly_ohlc


class TpexOhlcProvider(Protocol):
    def fetch_monthly_index_ohlc(self, month: date | str) -> ProviderPayload: ...


class TpexOhlcArchive(Protocol):
    def archive(
        self,
        batch: NormalizedTpexOhlcBatch,
        *,
        backfill_task_id: int,
    ) -> HistoricalArchiveWriteResult: ...


@final
class TpexOhlcLandingService:
    def __init__(
        self,
        *,
        provider: TpexOhlcProvider,
        archive_service: TpexOhlcArchive,
    ) -> None:
        self.provider = provider
        self.archive_service = archive_service

    def land(
        self,
        *,
        month: date,
        backfill_task_id: int,
    ) -> TpexOhlcLandingResult:
        payload = self.provider.fetch_monthly_index_ohlc(month)
        batch = normalize_tpex_monthly_ohlc(payload)
        archived = self.archive_service.archive(
            batch,
            backfill_task_id=backfill_task_id,
        )
        return TpexOhlcLandingResult(
            fetched_rows=len(batch.rows),
            archived_rows=archived.row_count,
            latest_trade_date=max(row.trade_date for row in batch.rows).isoformat(),
            source_payload_hash=batch.source_payload_sha256,
            object_key=archived.object_key,
            object_created=archived.created,
            byte_size=archived.byte_size,
        )
