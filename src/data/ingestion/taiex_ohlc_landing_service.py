"""Fetch, normalize, and archive one completed TAIEX calendar month."""

from __future__ import annotations

from datetime import date
from typing import Protocol, final

from src.data.providers.contracts import ProviderPayload

from .historical_daily_bar_archive_service import HistoricalArchiveWriteResult
from .taiex_ohlc_backfill_contracts import TaiexOhlcLandingResult
from .taiex_ohlc_contracts import NormalizedTaiexOhlcBatch
from .taiex_ohlc_normalizer import normalize_taiex_monthly_ohlc


class TaiexOhlcProvider(Protocol):
    def fetch_taiex_monthly_ohlc(self, month: date | str) -> ProviderPayload: ...


class TaiexOhlcArchive(Protocol):
    def archive(
        self,
        batch: NormalizedTaiexOhlcBatch,
        *,
        backfill_task_id: int,
    ) -> HistoricalArchiveWriteResult: ...


@final
class TaiexOhlcLandingService:
    def __init__(
        self,
        *,
        provider: TaiexOhlcProvider,
        archive_service: TaiexOhlcArchive,
    ) -> None:
        self.provider = provider
        self.archive_service = archive_service

    def land(
        self,
        *,
        month: date,
        backfill_task_id: int,
    ) -> TaiexOhlcLandingResult:
        payload = self.provider.fetch_taiex_monthly_ohlc(month)
        batch = normalize_taiex_monthly_ohlc(payload)
        archived = self.archive_service.archive(
            batch,
            backfill_task_id=backfill_task_id,
        )
        return TaiexOhlcLandingResult(
            fetched_rows=len(batch.rows),
            archived_rows=archived.row_count,
            latest_trade_date=max(row.trade_date for row in batch.rows).isoformat(),
            source_payload_hash=batch.source_payload_sha256,
            object_key=archived.object_key,
            object_created=archived.created,
            byte_size=archived.byte_size,
        )
