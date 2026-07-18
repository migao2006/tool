"""Fetch-first, idempotent first-stage import for Taiwan ordinary stocks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol, cast, final

from src.data.providers.contracts import ProviderPayload
from src.data.providers.registry import build_provider_registry
from src.data.providers.settings import ApiProviderSettings

from .contracts import ImportSummary, IngestionError
from .normalizers import (
    data_source_rows,
    normalize_company_profiles,
    normalize_daily_bars,
    revision_version,
)
from .parallel_fetch import PayloadFetchRequest, fetch_provider_payloads
from .quality import validate_first_stage_batch
from .returned_ids import returned_id_map, returned_security_id_map
from .supabase_writer import SupabaseWriter


class DailyProvider(Protocol):
    def fetch(self, dataset: str) -> ProviderPayload: ...


class DailyWriter(Protocol):
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


@final
class DailyMarketImporter:
    """Imports current source snapshots without pretending they are historical vintages."""

    def __init__(
        self,
        *,
        settings: ApiProviderSettings,
        registry: Mapping[str, DailyProvider] | None = None,
        writer: DailyWriter | None = None,
    ) -> None:
        self.settings = settings
        providers = registry or cast(
            Mapping[str, DailyProvider],
            build_provider_registry(settings),
        )
        self.registry = dict(providers)
        self.writer = writer

    def _writer(self) -> DailyWriter:
        if self.writer is None:
            self.writer = SupabaseWriter(
                url=self.settings.supabase_url,
                server_key=self.settings.supabase_service_role_key,
                timeout=max(self.settings.timeout_seconds, 30.0),
            )
        return self.writer

    def run(self, *, as_of_date: date, dry_run: bool = False) -> ImportSummary:
        mops = self.registry["MOPS"]
        twse = self.registry["TWSE"]
        tpex = self.registry["TPEX"]

        # Fetch every required payload before the first write. A provider failure
        # therefore cannot leave a falsely complete daily batch.
        payloads = fetch_provider_payloads(
            {
                "mops_listed_profiles": PayloadFetchRequest(
                    "MOPS", mops, "listed_company_profile"
                ),
                "mops_otc_profiles": PayloadFetchRequest(
                    "MOPS", mops, "otc_company_profile"
                ),
                "twse_daily_bars": PayloadFetchRequest(
                    "TWSE", twse, "daily_bars"
                ),
                "tpex_daily_bars": PayloadFetchRequest(
                    "TPEX", tpex, "daily_bars"
                ),
            }
        )
        fetched = {
            name: int(payload.record_count or 0)
            for name, payload in payloads.items()
        }

        source_rows = data_source_rows()
        provisional_source_ids = {"MOPS": 1, "TWSE": 2, "TPEX": 3}

        # Normalize with provisional IDs so every quality gate runs before the
        # first external write. Actual database IDs are substituted afterwards.
        listed, excluded_listed = normalize_company_profiles(
            payloads["mops_listed_profiles"],
            market="TWSE",
            source_id=provisional_source_ids["MOPS"],
        )
        otc, excluded_otc = normalize_company_profiles(
            payloads["mops_otc_profiles"],
            market="TPEX",
            source_id=provisional_source_ids["MOPS"],
        )
        provisional_securities = [*listed, *otc]
        provisional_security_ids = {
            (str(row["market"]), str(row["symbol"])): index
            for index, row in enumerate(provisional_securities, start=1)
        }
        provisional_twse_bars, excluded_twse_bars = normalize_daily_bars(
            payloads["twse_daily_bars"],
            market="TWSE",
            source_id=provisional_source_ids["TWSE"],
            security_ids=provisional_security_ids,
        )
        provisional_tpex_bars, excluded_tpex_bars = normalize_daily_bars(
            payloads["tpex_daily_bars"],
            market="TPEX",
            source_id=provisional_source_ids["TPEX"],
            security_ids=provisional_security_ids,
        )
        quality = validate_first_stage_batch(
            requested_as_of_date=as_of_date,
            listed_securities=listed,
            otc_securities=otc,
            twse_bars=provisional_twse_bars,
            tpex_bars=provisional_tpex_bars,
        )

        source_ids = provisional_source_ids
        securities = provisional_securities
        twse_bars = provisional_twse_bars
        tpex_bars = provisional_tpex_bars
        if not dry_run:
            written_sources = self._writer().upsert(
                "data_sources",
                source_rows,
                on_conflict="source_code",
                select="source_id,source_code",
                return_rows=True,
            )
            source_ids = returned_id_map(
                written_sources,
                code_key="source_code",
                id_key="source_id",
            )
            if set(source_ids) != {"MOPS", "TWSE", "TPEX"}:
                raise IngestionError(
                    "DATA_SOURCE_UPSERT_INCOMPLETE",
                    "Supabase did not return every required data source",
                )

            securities = [
                {**row, "source_id": source_ids["MOPS"]}
                for row in provisional_securities
            ]
            written_securities = self._writer().upsert(
                "securities",
                securities,
                on_conflict="market,symbol",
                select="security_id,market,symbol",
                return_rows=True,
            )
            security_ids = returned_security_id_map(written_securities)
            if len(security_ids) != len(securities):
                raise IngestionError(
                    "SECURITY_MASTER_UPSERT_INCOMPLETE",
                    "Supabase did not return every normalized security",
                )

            twse_bars, _ = normalize_daily_bars(
                payloads["twse_daily_bars"],
                market="TWSE",
                source_id=source_ids["TWSE"],
                security_ids=security_ids,
            )
            tpex_bars, _ = normalize_daily_bars(
                payloads["tpex_daily_bars"],
                market="TPEX",
                source_id=source_ids["TPEX"],
                security_ids=security_ids,
            )
        bars = [*twse_bars, *tpex_bars]

        database_counts: dict[str, int] = {}
        if not dry_run:
            _ = self._writer().upsert(
                "daily_bars",
                bars,
                on_conflict="security_id,trade_date,source_id,source_version",
                preserve_existing=True,
            )
            self._writer().refresh_home_data_status()
            database_counts = {
                table: self._writer().count_rows(table)
                for table in ("data_sources", "securities", "daily_bars")
            }

        return ImportSummary(
            as_of_date=quality.source_date,
            requested_as_of_date=as_of_date,
            dry_run=dry_run,
            fetched_records=fetched,
            normalized_records={
                "data_sources": len(source_rows),
                "securities": len(securities),
                "daily_bars": len(bars),
            },
            excluded_records={
                "listed_profiles": excluded_listed,
                "otc_profiles": excluded_otc,
                "twse_daily_bars": excluded_twse_bars,
                "tpex_daily_bars": excluded_tpex_bars,
            },
            database_counts=database_counts,
            source_versions={
                name: revision_version(payload)
                for name, payload in payloads.items()
            },
            source_dates=quality.source_dates,
        )
