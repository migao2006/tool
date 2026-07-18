"""Bounded FinMind-to-Supabase historical daily-bar landing importer."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from time import sleep
from typing import Protocol, cast, final

from src.data.providers.contracts import ProviderPayload
from src.data.providers.finmind import FinMindClient
from src.data.providers.settings import ApiProviderSettings

from .contracts import IngestionError
from .finmind_historical_probe import validate_probe_request
from .historical_daily_bar_contracts import NormalizedHistoricalDailyBarBatch
from .historical_daily_bar_import_contracts import HistoricalDailyBarImportSummary
from .historical_daily_bar_normalizer import normalize_historical_daily_bars
from .returned_ids import returned_id_map
from .source_catalog import finmind_data_source_row
from .supabase_writer import SupabaseWriter


IMPORT_REASON_CODES = (
    "REQUEST_UNIVERSE_NOT_POINT_IN_TIME",
    "HISTORICAL_VINTAGE_UNAVAILABLE",
    "IDENTITY_UNRESOLVED",
    "RAW_LANDING_ONLY",
)


class HistoricalBarProvider(Protocol):
    def fetch_quota(self) -> ProviderPayload: ...

    def fetch(
        self,
        dataset: str,
        *,
        data_id: str | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> ProviderPayload: ...


class HistoricalBarWriter(Protocol):
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

    def count_rows(self, table: str) -> int: ...


def _quota_remaining(payload: ProviderPayload) -> int:
    raw = cast(object, payload.payload)
    if not isinstance(raw, Mapping):
        raise IngestionError(
            "FINMIND_QUOTA_PAYLOAD_INVALID",
            "FinMind quota response must be an object",
        )
    body = cast(Mapping[str, object], raw)
    used = body.get("user_count")
    limit = body.get("api_request_limit")
    if (
        isinstance(used, bool)
        or not isinstance(used, int)
        or isinstance(limit, bool)
        or not isinstance(limit, int)
    ):
        raise IngestionError(
            "FINMIND_QUOTA_PAYLOAD_INVALID",
            "FinMind quota response is missing documented counters",
        )
    return max(limit - used, 0)


def _source_id(rows: Sequence[Mapping[str, object]]) -> int:
    source_ids = returned_id_map(
        rows,
        code_key="source_code",
        id_key="source_id",
    )
    if set(source_ids) != {"FINMIND"}:
        raise IngestionError(
            "DATA_SOURCE_UPSERT_INCOMPLETE",
            "Supabase did not return the FinMind source identifier",
        )
    return source_ids["FINMIND"]


def _for_database(
    rows: Sequence[Mapping[str, object]],
    *,
    source_id: int,
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
) -> None:
    if not rows:
        raise IngestionError(
            "HISTORICAL_DAILY_BAR_EMPTY_RESPONSE",
            f"FinMind returned no daily bars for {symbol}",
        )
    for row in rows:
        if row.get("parse_status") != "PARSED":
            continue
        if row.get("source_symbol") != symbol:
            raise IngestionError(
                "HISTORICAL_DAILY_BAR_SYMBOL_MISMATCH",
                "FinMind returned a parsed row for another symbol",
            )
        raw_trade_date = row.get("trade_date")
        if not isinstance(raw_trade_date, str):
            raise IngestionError(
                "HISTORICAL_DAILY_BAR_DATE_INVALID",
                "A parsed historical bar is missing trade_date",
            )
        trade_date = date.fromisoformat(raw_trade_date)
        if not start_date <= trade_date <= end_date:
            raise IngestionError(
                "HISTORICAL_DAILY_BAR_DATE_OUTSIDE_REQUEST",
                "FinMind returned a parsed row outside the requested range",
            )


@final
class HistoricalDailyBarImporter:
    """Land a small explicit symbol batch without identity or PIT promotion."""

    def __init__(
        self,
        *,
        settings: ApiProviderSettings,
        provider: HistoricalBarProvider | None = None,
        writer: HistoricalBarWriter | None = None,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        self.settings = settings
        self.provider = provider or FinMindClient(token=settings.finmind_token)
        self.writer = writer
        self._sleep = sleep_fn

    def _writer(self) -> HistoricalBarWriter:
        if self.writer is None:
            self.writer = SupabaseWriter(
                url=self.settings.supabase_url,
                server_key=self.settings.supabase_service_role_key,
                timeout=max(self.settings.timeout_seconds, 30.0),
            )
        return self.writer

    def run(
        self,
        *,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
        pacing_seconds: float = 7.5,
        dry_run: bool = False,
    ) -> HistoricalDailyBarImportSummary:
        normalized_symbols = validate_probe_request(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            pacing_seconds=pacing_seconds,
        )
        if _quota_remaining(self.provider.fetch_quota()) < len(normalized_symbols):
            raise IngestionError(
                "FINMIND_IMPORT_QUOTA_INSUFFICIENT",
                "FinMind quota is insufficient for this bounded import",
            )

        fetched_rows = landed_rows = quarantined_rows = quarantine_issues = 0
        payload_hashes: list[str] = []
        batches: list[NormalizedHistoricalDailyBarBatch] = []
        for index, symbol in enumerate(normalized_symbols):
            if index and pacing_seconds:
                self._sleep(pacing_seconds)
            payload = self.provider.fetch(
                "daily_bars",
                data_id=symbol,
                start_date=start_date,
                end_date=end_date,
            )
            batch = normalize_historical_daily_bars(payload)
            _validate_source_scope(
                batch.landing_rows,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
            )
            fetched_rows += batch.source_row_count
            landed_rows += len(batch.landing_rows)
            quarantined_rows += sum(
                row.get("parse_status") == "QUARANTINED" for row in batch.landing_rows
            )
            quarantine_issues += len(batch.quarantine_rows)
            payload_hashes.append(payload.payload_sha256)
            batches.append(batch)

        if not dry_run:
            returned = self._writer().upsert(
                "data_sources",
                [finmind_data_source_row()],
                on_conflict="source_code",
                select="source_id,source_code",
                return_rows=True,
            )
            source_id = _source_id(returned)
            for batch in batches:
                landing = _for_database(batch.landing_rows, source_id=source_id)
                _ = self._writer().upsert(
                    "historical_daily_bar_landing",
                    landing,
                    on_conflict="landing_key",
                    preserve_existing=True,
                )
                if batch.quarantine_rows:
                    _ = self._writer().upsert(
                        "historical_daily_bar_quarantine",
                        batch.quarantine_rows,
                        on_conflict="landing_key,reason_code,field_name",
                        preserve_existing=True,
                    )

        database_counts = (
            {}
            if dry_run
            else {
                table: self._writer().count_rows(table)
                for table in (
                    "historical_daily_bar_landing",
                    "historical_daily_bar_quarantine",
                )
            }
        )
        return HistoricalDailyBarImportSummary(
            dry_run=dry_run,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            requested_symbols=normalized_symbols,
            fetched_rows=fetched_rows,
            landed_rows=landed_rows,
            quarantined_rows=quarantined_rows,
            quarantine_issues=quarantine_issues,
            source_payload_hashes=tuple(payload_hashes),
            database_counts=database_counts,
            reason_codes=IMPORT_REASON_CODES,
        )
