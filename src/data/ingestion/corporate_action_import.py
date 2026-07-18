"""Fetch-first importer for current official corporate-action forecasts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol, cast, final
from zoneinfo import ZoneInfo

from src.data.providers.contracts import ProviderPayload
from src.data.providers.registry import build_provider_registry
from src.data.providers.settings import ApiProviderSettings

from .contracts import IngestionError
from .corporate_action_contracts import (
    CORPORATE_ACTION_REASON_CODES,
    CorporateActionImportSummary,
    NormalizedCorporateActions,
)
from .corporate_actions import normalize_announced_corporate_actions
from .normalizers import (
    data_source_rows,
    normalize_company_profiles,
    revision_version,
)
from .parallel_fetch import PayloadFetchRequest, fetch_provider_payloads
from .quality import MIN_SECURITIES_PER_MARKET
from .returned_ids import returned_id_map, returned_security_id_map
from .supabase_writer import SupabaseWriter


TAIPEI = ZoneInfo("Asia/Taipei")
SNAPSHOT_DATE_MISMATCH = "SNAPSHOT_DATE_DOES_NOT_MATCH_RETRIEVAL_DATE"


class CorporateActionProvider(Protocol):
    def fetch(self, dataset: str) -> ProviderPayload: ...


class CorporateActionWriter(Protocol):
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
class CorporateActionImporter:
    """Save observed forecast revisions without claiming historical coverage."""

    def __init__(
        self,
        *,
        settings: ApiProviderSettings,
        registry: Mapping[str, CorporateActionProvider] | None = None,
        writer: CorporateActionWriter | None = None,
    ) -> None:
        self.settings = settings
        providers = registry or cast(
            Mapping[str, CorporateActionProvider],
            build_provider_registry(settings),
        )
        self.registry = dict(providers)
        self.writer = writer

    def _writer(self) -> CorporateActionWriter:
        if self.writer is None:
            self.writer = SupabaseWriter(
                url=self.settings.supabase_url,
                server_key=self.settings.supabase_service_role_key,
                timeout=max(self.settings.timeout_seconds, 30.0),
            )
        return self.writer

    def _fetch_all(self) -> dict[str, ProviderPayload]:
        mops = self.registry["MOPS"]
        twse = self.registry["TWSE"]
        tpex = self.registry["TPEX"]
        return fetch_provider_payloads(
            {
                "mops_listed_profiles": PayloadFetchRequest(
                    "MOPS", mops, "listed_company_profile"
                ),
                "mops_otc_profiles": PayloadFetchRequest(
                    "MOPS", mops, "otc_company_profile"
                ),
                "twse_ex_rights_forecast": PayloadFetchRequest(
                    "TWSE", twse, "ex_rights"
                ),
                "tpex_ex_rights_forecast": PayloadFetchRequest(
                    "TPEX", tpex, "ex_rights_forecast"
                ),
            }
        )

    @staticmethod
    def _securities(
        payloads: Mapping[str, ProviderPayload],
        *,
        source_id: int,
    ) -> tuple[list[dict[str, object]], dict[str, int]]:
        listed, excluded_listed = normalize_company_profiles(
            payloads["mops_listed_profiles"], market="TWSE", source_id=source_id
        )
        otc, excluded_otc = normalize_company_profiles(
            payloads["mops_otc_profiles"], market="TPEX", source_id=source_id
        )
        if min(len(listed), len(otc)) < MIN_SECURITIES_PER_MARKET:
            raise IngestionError(
                "SECURITY_MASTER_COVERAGE_TOO_LOW",
                "Current company profiles are below the minimum market coverage",
            )
        return [*listed, *otc], {
            "listed_profiles": excluded_listed,
            "otc_profiles": excluded_otc,
        }

    @staticmethod
    def _normalize_actions(
        payloads: Mapping[str, ProviderPayload],
        *,
        source_ids: Mapping[str, int],
        security_ids: Mapping[tuple[str, str], int],
    ) -> dict[str, NormalizedCorporateActions]:
        return {
            "TWSE": normalize_announced_corporate_actions(
                payloads["twse_ex_rights_forecast"],
                market="TWSE",
                source_id=source_ids["TWSE"],
                security_ids=security_ids,
            ),
            "TPEX": normalize_announced_corporate_actions(
                payloads["tpex_ex_rights_forecast"],
                market="TPEX",
                source_id=source_ids["TPEX"],
                security_ids=security_ids,
            ),
        }

    def run(
        self,
        *,
        snapshot_date: date,
        dry_run: bool = False,
    ) -> CorporateActionImportSummary:
        payloads = self._fetch_all()
        source_rows = data_source_rows()
        provisional_source_ids = {"MOPS": 1, "TWSE": 2, "TPEX": 3}
        securities, profile_exclusions = self._securities(
            payloads, source_id=provisional_source_ids["MOPS"]
        )
        provisional_security_ids = {
            (str(row["market"]), str(row["symbol"])): index
            for index, row in enumerate(securities, start=1)
        }
        actions = self._normalize_actions(
            payloads,
            source_ids=provisional_source_ids,
            security_ids=provisional_security_ids,
        )
        retrieval_dates = {
            name: payload.retrieved_at.astimezone(TAIPEI).date()
            for name, payload in payloads.items()
        }
        retrieval_date_matches = all(
            observed == snapshot_date for observed in retrieval_dates.values()
        )
        if not dry_run and not retrieval_date_matches:
            raise IngestionError(
                "CORPORATE_ACTION_SNAPSHOT_DATE_INVALID",
                "Snapshot date must equal every source retrieval date",
            )

        if not dry_run:
            returned_sources = self._writer().upsert(
                "data_sources",
                source_rows,
                on_conflict="source_code",
                select="source_id,source_code",
                return_rows=True,
            )
            source_ids = returned_id_map(
                returned_sources, code_key="source_code", id_key="source_id"
            )
            if set(source_ids) != {"MOPS", "TWSE", "TPEX"}:
                raise IngestionError(
                    "DATA_SOURCE_UPSERT_INCOMPLETE",
                    "Supabase did not return every corporate-action data source",
                )
            securities = [
                {**row, "source_id": source_ids["MOPS"]} for row in securities
            ]
            returned_securities = self._writer().upsert(
                "securities",
                securities,
                on_conflict="market,symbol",
                select="security_id,market,symbol",
                return_rows=True,
            )
            security_ids = returned_security_id_map(returned_securities)
            if len(security_ids) != len(securities):
                raise IngestionError(
                    "SECURITY_MASTER_UPSERT_INCOMPLETE",
                    "Supabase did not return every normalized security",
                )
            actions = self._normalize_actions(
                payloads,
                source_ids=source_ids,
                security_ids=security_ids,
            )
            rows = [row for market in ("TWSE", "TPEX") for row in actions[market].rows]
            if rows:
                _ = self._writer().upsert(
                    "corporate_actions",
                    rows,
                    on_conflict="source_id,source_event_id,source_revision_hash",
                    preserve_existing=True,
                )
            self._writer().refresh_home_data_status()

        action_rows = sum(len(item.rows) for item in actions.values())
        database_counts = (
            {}
            if dry_run
            else {
                table: self._writer().count_rows(table)
                for table in ("data_sources", "securities", "corporate_actions")
            }
        )
        source_dates = {
            f"{name}_retrieved": value.isoformat()
            for name, value in retrieval_dates.items()
        }
        for market, normalized in actions.items():
            source_dates[f"{market.lower()}_observed_ex_date_min"] = (
                normalized.observed_ex_date_min.isoformat()
                if normalized.observed_ex_date_min
                else "UNAVAILABLE"
            )
            source_dates[f"{market.lower()}_observed_ex_date_max"] = (
                normalized.observed_ex_date_max.isoformat()
                if normalized.observed_ex_date_max
                else "UNAVAILABLE"
            )
        return CorporateActionImportSummary(
            snapshot_date=snapshot_date,
            dry_run=dry_run,
            fetched_records={
                name: int(payload.record_count or 0)
                for name, payload in payloads.items()
            },
            normalized_records={
                "data_sources": len(source_rows),
                "securities": len(securities),
                "corporate_actions": action_rows,
            },
            excluded_records={
                **profile_exclusions,
                "unknown_securities": sum(
                    item.excluded_unknown_securities for item in actions.values()
                ),
                "no_supported_component": sum(
                    item.excluded_no_supported_component_rows
                    for item in actions.values()
                ),
                "omitted_rights_components": sum(
                    item.omitted_rights_components for item in actions.values()
                ),
                "unresolved_announced_components": sum(
                    item.unresolved_announced_components for item in actions.values()
                ),
            },
            database_counts=database_counts,
            source_versions={
                name: revision_version(payload) for name, payload in payloads.items()
            },
            source_dates=source_dates,
            latest_available_at=max(
                payload.retrieved_at for payload in payloads.values()
            ),
            reason_codes=(
                CORPORATE_ACTION_REASON_CODES
                if retrieval_date_matches
                else (*CORPORATE_ACTION_REASON_CODES, SNAPSHOT_DATE_MISMATCH)
            ),
        )
