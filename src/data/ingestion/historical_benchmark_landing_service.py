"""Fetch exactly one FinMind TAIEX benchmark response and archive it."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol, final

from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError
from .historical_benchmark_contracts import (
    BENCHMARK_DATASET,
    BENCHMARK_DATA_ID,
    HistoricalBenchmarkLandingResult,
)
from .historical_benchmark_normalizer import normalize_historical_benchmark
from .historical_daily_bar_archive_service import HistoricalArchiveWriteResult


class HistoricalBenchmarkProvider(Protocol):
    def fetch(
        self,
        dataset: str,
        *,
        data_id: str | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> ProviderPayload: ...


class HistoricalBenchmarkArchive(Protocol):
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


@final
class HistoricalBenchmarkLandingService:
    def __init__(
        self,
        *,
        provider: HistoricalBenchmarkProvider,
        archive_service: HistoricalBenchmarkArchive,
    ) -> None:
        self.provider = provider
        self.archive_service = archive_service

    def land(
        self,
        *,
        start_date: date,
        end_date: date,
        backfill_task_id: int,
    ) -> HistoricalBenchmarkLandingResult:
        payload = self.provider.fetch(
            BENCHMARK_DATASET,
            data_id=BENCHMARK_DATA_ID,
            start_date=start_date,
            end_date=end_date,
        )
        batch = normalize_historical_benchmark(payload)
        parsed_dates = [
            date.fromisoformat(str(row["trade_date"]))
            for row in batch.landing_rows
            if row.get("parse_status") == "PARSED"
        ]
        if not parsed_dates:
            raise IngestionError(
                "HISTORICAL_BENCHMARK_NO_PARSED_ROWS",
                "FinMind returned no valid TAIEX total-return observations",
            )
        if any(value < start_date or value > end_date for value in parsed_dates):
            raise IngestionError(
                "HISTORICAL_BENCHMARK_DATE_OUTSIDE_REQUEST",
                "FinMind returned a benchmark date outside the requested range",
            )
        archived = self.archive_service.archive(
            rows=batch.landing_rows,
            quarantine_rows=batch.quarantine_rows,
            payload=payload,
            scheduled_market="TWSE",
            asset_type="BENCHMARK",
            symbol=BENCHMARK_DATA_ID,
            start_date=start_date,
            end_date=end_date,
            backfill_task_id=backfill_task_id,
        )
        return HistoricalBenchmarkLandingResult(
            fetched_rows=batch.source_row_count,
            archived_rows=archived.row_count,
            quarantined_rows=batch.quarantined_count,
            quarantine_issues=len(batch.quarantine_rows),
            latest_trade_date=max(parsed_dates).isoformat(),
            source_payload_hash=payload.payload_sha256,
            object_key=archived.object_key,
        )
