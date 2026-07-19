"""Fetch and archive one FinMind supplemental dataset for one TWSE symbol."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol, final

from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError
from .historical_daily_bar_archive_service import HistoricalArchiveWriteResult
from .historical_daily_bar_import_contracts import HistoricalSymbolLandingResult
from .historical_supplemental_contracts import SUPPLEMENTAL_DATASETS
from .historical_supplemental_normalizer import (
    normalize_historical_supplemental,
)


class SupplementalProvider(Protocol):
    def fetch(
        self,
        dataset: str,
        *,
        data_id: str | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> ProviderPayload: ...


class SupplementalArchive(Protocol):
    def archive(
        self,
        *,
        rows: Sequence[Mapping[str, object]],
        quarantine_rows: Sequence[Mapping[str, object]],
        payload: ProviderPayload,
        scheduled_market: str,
        asset_type: str,
        symbol: str,
        start_date: date,
        end_date: date,
        backfill_task_id: int | None,
    ) -> HistoricalArchiveWriteResult: ...


def _latest_trade_date(
    rows: Sequence[Mapping[str, object]],
    *,
    symbol: str,
    start_date: date,
    end_date: date,
) -> str:
    if not rows:
        raise IngestionError(
            "HISTORICAL_SUPPLEMENTAL_EMPTY_RESPONSE",
            f"FinMind returned no supplemental rows for {symbol}",
        )
    latest: date | None = None
    for row in rows:
        row_symbol = row.get("source_symbol")
        raw_trade_date = row.get("trade_date")
        if row_symbol is None or not isinstance(raw_trade_date, str):
            continue
        if row_symbol != symbol:
            raise IngestionError(
                "HISTORICAL_SUPPLEMENTAL_SYMBOL_MISMATCH",
                "FinMind returned a row for another symbol",
            )
        trade_date = date.fromisoformat(raw_trade_date)
        if not start_date <= trade_date <= end_date:
            raise IngestionError(
                "HISTORICAL_SUPPLEMENTAL_DATE_OUTSIDE_REQUEST",
                "FinMind returned a row outside the requested range",
            )
        latest = max(latest or trade_date, trade_date)
    if latest is None:
        raise IngestionError(
            "HISTORICAL_SUPPLEMENTAL_NO_PARSED_ROWS",
            f"FinMind returned no valid supplemental rows for {symbol}",
        )
    return latest.isoformat()


@final
class HistoricalSupplementalLandingService:
    def __init__(
        self,
        *,
        provider: SupplementalProvider,
        archive_service: SupplementalArchive,
    ) -> None:
        self.provider = provider
        self.archive_service = archive_service

    def land_symbol(
        self,
        *,
        dataset: str,
        symbol: str,
        start_date: date,
        end_date: date,
        scheduled_market: str,
        asset_type: str,
        backfill_task_id: int | None,
    ) -> HistoricalSymbolLandingResult:
        if dataset not in SUPPLEMENTAL_DATASETS:
            raise ValueError("unsupported supplemental dataset")
        if scheduled_market != "TWSE" or asset_type != "COMMON_STOCK":
            raise IngestionError(
                "HISTORICAL_SUPPLEMENTAL_SCOPE_INVALID",
                "The first supplemental backfill phase is TWSE common stocks only",
            )
        payload = self.provider.fetch(
            dataset,
            data_id=symbol,
            start_date=start_date,
            end_date=end_date,
        )
        batch = normalize_historical_supplemental(payload)
        latest_trade_date = _latest_trade_date(
            batch.landing_rows,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )
        _ = self.archive_service.archive(
            rows=batch.landing_rows,
            quarantine_rows=batch.quarantine_rows,
            payload=payload,
            scheduled_market=scheduled_market,
            asset_type=asset_type,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            backfill_task_id=backfill_task_id,
        )
        return HistoricalSymbolLandingResult(
            symbol=symbol,
            fetched_rows=batch.source_row_count,
            landed_rows=len(batch.landing_rows),
            quarantined_rows=batch.quarantined_count,
            quarantine_issues=len(batch.quarantine_rows),
            latest_trade_date=latest_trade_date,
            source_payload_hash=payload.payload_sha256,
        )
