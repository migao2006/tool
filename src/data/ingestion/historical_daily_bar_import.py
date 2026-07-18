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
from .historical_daily_bar_import_contracts import HistoricalDailyBarImportSummary
from .historical_daily_bar_landing_service import HistoricalDailyBarLandingService
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

    def refresh_home_data_status(self) -> None: ...


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
        landing_service = HistoricalDailyBarLandingService(
            provider=self.provider,
            writer=None if dry_run else self._writer(),
            dry_run=dry_run,
        )
        for index, symbol in enumerate(normalized_symbols):
            if index and pacing_seconds:
                self._sleep(pacing_seconds)
            result = landing_service.land_symbol(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
            )
            fetched_rows += result.fetched_rows
            landed_rows += result.landed_rows
            quarantined_rows += result.quarantined_rows
            quarantine_issues += result.quarantine_issues
            payload_hashes.append(result.source_payload_hash)

        if not dry_run:
            landing_service.refresh_home_status()

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
