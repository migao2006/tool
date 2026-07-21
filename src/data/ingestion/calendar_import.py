"""Fetch-first, idempotent historical trading-calendar importer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol, cast, final

from src.data.providers.contracts import ProviderPayload
from src.data.providers.registry import build_provider_registry
from src.data.providers.settings import ApiProviderSettings

from .calendar_contracts import CalendarImportSummary
from .calendar_observations import (
    DATE_ONLY_REASON_CODES,
    normalize_finmind_calendar_observations,
)
from .contracts import IngestionError
from .normalizers import revision_version
from .source_catalog import finmind_data_source_row
from .supabase_writer import SupabaseWriter
from .trading_calendar import normalize_finmind_trading_calendar


MINIMUM_RESEARCH_HISTORY_DAYS = 7 * 365


class CalendarWriter(Protocol):
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


class CalendarProvider(Protocol):
    def fetch(
        self,
        dataset: str,
        *,
        start_date: date,
        end_date: date,
    ) -> ProviderPayload: ...


@final
class TradingCalendarImporter:
    """Import only sessions proven by the selected provider response."""

    def __init__(
        self,
        *,
        settings: ApiProviderSettings,
        registry: Mapping[str, CalendarProvider] | None = None,
        writer: CalendarWriter | None = None,
    ) -> None:
        self.settings = settings
        provider_registry = registry or cast(
            Mapping[str, CalendarProvider],
            build_provider_registry(settings),
        )
        self.registry = dict(provider_registry)
        self.writer = writer

    def _writer(self) -> CalendarWriter:
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
        start_date: date,
        end_date: date,
        markets: Sequence[str] = ("TWSE",),
        dry_run: bool = False,
    ) -> CalendarImportSummary:
        if start_date > end_date:
            raise ValueError("start_date must not be later than end_date")

        payload = self.registry["FINMIND"].fetch(
            "trading_calendar",
            start_date=start_date,
            end_date=end_date,
        )
        normalized = normalize_finmind_trading_calendar(
            payload,
            start_date=start_date,
            end_date=end_date,
            source_id=1,
            markets=markets,
        )
        observations = normalize_finmind_calendar_observations(
            payload,
            normalized,
            source_id=1,
        )

        if not dry_run:
            returned_sources = self._writer().upsert(
                "data_sources",
                [finmind_data_source_row()],
                on_conflict="source_code",
                select="source_id,source_code",
                return_rows=True,
            )
            matching_sources = [
                row for row in returned_sources if row.get("source_code") == "FINMIND"
            ]
            if len(matching_sources) != 1:
                raise IngestionError(
                    "DATA_SOURCE_UPSERT_INCOMPLETE",
                    "Supabase did not return the FinMind data source",
                )
            raw_source_id = matching_sources[0].get("source_id")
            if isinstance(raw_source_id, bool) or not isinstance(
                raw_source_id, (int, str)
            ):
                raise IngestionError(
                    "DATA_SOURCE_UPSERT_INCOMPLETE",
                    "Supabase returned an invalid FinMind source identifier",
                )
            try:
                source_id = int(raw_source_id)
            except ValueError as error:
                raise IngestionError(
                    "DATA_SOURCE_UPSERT_INCOMPLETE",
                    "Supabase returned an invalid FinMind source identifier",
                ) from error
            normalized = normalize_finmind_trading_calendar(
                payload,
                start_date=start_date,
                end_date=end_date,
                source_id=source_id,
                markets=markets,
            )
            observations = normalize_finmind_calendar_observations(
                payload,
                normalized,
                source_id=source_id,
            )
            _ = self._writer().upsert(
                "trading_calendar",
                normalized,
                on_conflict="market,trading_date",
                preserve_existing=True,
            )
            _ = self._writer().upsert(
                "trading_calendar_observations",
                observations,
                on_conflict=(
                    "source_id,source_dataset,source_event_id,market,"
                    "trading_date,source_revision_hash"
                ),
                preserve_existing=True,
            )
            self._writer().refresh_home_data_status()

        session_dates = sorted(
            {date.fromisoformat(str(row["trading_date"])) for row in normalized}
        )
        reason_codes = [
            "TPEX_CALENDAR_SOURCE_NOT_VERIFIED",
            *DATE_ONLY_REASON_CODES,
        ]
        if (end_date - start_date).days < MINIMUM_RESEARCH_HISTORY_DAYS:
            reason_codes.append("HISTORICAL_RANGE_BELOW_SEVEN_YEARS")

        return CalendarImportSummary(
            requested_start_date=start_date,
            requested_end_date=end_date,
            coverage_start_date=session_dates[0],
            coverage_end_date=session_dates[-1],
            dry_run=dry_run,
            markets=tuple(dict.fromkeys(str(market).upper() for market in markets)),
            fetched_dates=int(payload.record_count or 0),
            normalized_records=len(normalized),
            database_count=(
                None if dry_run else self._writer().count_rows("trading_calendar")
            ),
            observation_database_count=(
                None
                if dry_run
                else self._writer().count_rows("trading_calendar_observations")
            ),
            source_uri=payload.source_url,
            source_version=revision_version(payload),
            source_hash=payload.payload_sha256,
            retrieved_at=payload.retrieved_at,
            reason_codes=tuple(reason_codes),
        )
