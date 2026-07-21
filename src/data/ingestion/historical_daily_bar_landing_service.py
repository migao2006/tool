"""Fetch, validate, and immediately persist one historical symbol batch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol, final

from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError
from .historical_daily_bar_import_contracts import HistoricalSymbolLandingResult
from .historical_daily_bar_normalizer import normalize_historical_daily_bars
from .returned_ids import returned_id_map
from .source_catalog import finmind_data_source_row


class SymbolLandingProvider(Protocol):
    def fetch(
        self,
        dataset: str,
        *,
        data_id: str | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> ProviderPayload: ...


class SymbolLandingWriter(Protocol):
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

    def refresh_home_data_status(self) -> None: ...


class HistoricalSymbolArchive(Protocol):
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
    ) -> object: ...


def _source_id(rows: Sequence[Mapping[str, object]]) -> int:
    source_ids = returned_id_map(rows, code_key="source_code", id_key="source_id")
    if set(source_ids) != {"FINMIND"}:
        raise IngestionError(
            "DATA_SOURCE_UPSERT_INCOMPLETE",
            "Supabase did not return the FinMind source identifier",
        )
    return source_ids["FINMIND"]


def _for_database(
    rows: Sequence[Mapping[str, object]], *, source_id: int
) -> list[dict[str, object]]:
    prepared: list[dict[str, object]] = []
    for row in rows:
        value = dict(row)
        _ = value.pop("source_code", None)
        value["source_id"] = source_id
        prepared.append(value)
    return prepared


def _validate_source_scope(
    rows: Sequence[Mapping[str, object]],
    *,
    symbol: str,
    start_date: date,
    end_date: date,
) -> str:
    if not rows:
        raise IngestionError(
            "HISTORICAL_DAILY_BAR_EMPTY_RESPONSE",
            f"FinMind returned no daily bars for {symbol}",
        )
    latest_trade_date: date | None = None
    for row in rows:
        row_symbol = row.get("source_symbol")
        raw_trade_date = row.get("trade_date")
        if row_symbol is None or not isinstance(raw_trade_date, str):
            continue
        if row_symbol != symbol:
            raise IngestionError(
                "HISTORICAL_DAILY_BAR_SYMBOL_MISMATCH",
                "FinMind returned a row for another symbol",
            )
        parsed_trade_date = date.fromisoformat(raw_trade_date)
        if not start_date <= parsed_trade_date <= end_date:
            raise IngestionError(
                "HISTORICAL_DAILY_BAR_DATE_OUTSIDE_REQUEST",
                "FinMind returned a parsed row outside the requested range",
            )
        latest_trade_date = max(
            latest_trade_date or parsed_trade_date, parsed_trade_date
        )
    if latest_trade_date is None:
        raise IngestionError(
            "HISTORICAL_DAILY_BAR_NO_PARSED_ROWS",
            f"FinMind returned no valid daily bars for {symbol}",
        )
    return latest_trade_date.isoformat()


@final
class HistoricalDailyBarLandingService:
    """Persist each symbol independently so retries never discard completed work."""

    def __init__(
        self,
        *,
        provider: SymbolLandingProvider,
        writer: SymbolLandingWriter | None,
        archive_service: HistoricalSymbolArchive | None = None,
        dry_run: bool = False,
    ) -> None:
        self.provider = provider
        self.writer = writer
        self.archive_service = archive_service
        self.dry_run = dry_run
        self._source_id_value: int | None = None

    def _require_writer(self) -> SymbolLandingWriter:
        if self.writer is None:
            raise IngestionError(
                "SUPABASE_WRITE_CREDENTIALS_MISSING",
                "A writer is required for a non-dry-run landing import",
            )
        return self.writer

    def _ensure_source_id(self) -> int:
        if self._source_id_value is None:
            returned = self._require_writer().upsert(
                "data_sources",
                [finmind_data_source_row()],
                on_conflict="source_code",
                select="source_id,source_code",
                return_rows=True,
            )
            self._source_id_value = _source_id(returned)
        return self._source_id_value

    def land_symbol(
        self,
        *,
        symbol: str,
        start_date: date,
        end_date: date,
        scheduled_market: str | None = None,
        asset_type: str | None = None,
        backfill_task_id: int | None = None,
    ) -> HistoricalSymbolLandingResult:
        if (
            self.archive_service is not None
            and not self.dry_run
            and (not scheduled_market or not asset_type)
        ):
            raise IngestionError(
                "HISTORICAL_ARCHIVE_CONTEXT_MISSING",
                "Archive landing requires a scheduled market and asset type",
            )
        payload = self.provider.fetch(
            "daily_bars",
            data_id=symbol,
            start_date=start_date,
            end_date=end_date,
        )
        batch = normalize_historical_daily_bars(payload)
        latest_trade_date = _validate_source_scope(
            batch.landing_rows,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
        )
        if not self.dry_run:
            if self.archive_service is not None:
                assert scheduled_market is not None
                assert asset_type is not None
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
            else:
                source_id = self._ensure_source_id()
                landing = _for_database(batch.landing_rows, source_id=source_id)
                _ = self._require_writer().upsert(
                    "historical_daily_bar_landing",
                    landing,
                    on_conflict="landing_key",
                    preserve_existing=True,
                )
                if batch.quarantine_rows:
                    _ = self._require_writer().upsert(
                        "historical_daily_bar_quarantine",
                        batch.quarantine_rows,
                        on_conflict="landing_key,reason_code,field_name",
                        preserve_existing=True,
                    )
        quarantined_rows = sum(
            row.get("parse_status") == "QUARANTINED" for row in batch.landing_rows
        )
        return HistoricalSymbolLandingResult(
            symbol=symbol,
            fetched_rows=batch.source_row_count,
            landed_rows=len(batch.landing_rows),
            quarantined_rows=quarantined_rows,
            quarantine_issues=len(batch.quarantine_rows),
            latest_trade_date=latest_trade_date,
            source_payload_hash=payload.payload_sha256,
        )

    def refresh_home_status(self) -> None:
        if not self.dry_run:
            self._require_writer().refresh_home_data_status()
