"""Fetch-first importer for current official security-state snapshots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol, cast, final

from src.data.providers.contracts import ProviderPayload
from src.data.providers.registry import build_provider_registry
from src.data.providers.settings import ApiProviderSettings

from .contracts import IngestionError
from .normalizers import (
    data_source_rows,
    normalize_company_profiles,
    revision_version,
)
from .parallel_fetch import PayloadFetchRequest, fetch_provider_payloads
from .quality import MIN_SECURITIES_PER_MARKET
from .security_snapshot import (
    normalize_current_security_snapshot,
    resolve_coherent_profile_date,
    resolve_market_profile_date,
    snapshot_revision_hash,
)
from .security_snapshot_contracts import (
    MARKET_NON_SESSION_REASON,
    MarketSnapshotPayloads,
    NON_SESSION_REASON,
    SECURITY_SNAPSHOT_REASON_CODES,
    SecuritySnapshotSummary,
)
from .returned_ids import returned_id_map, returned_security_id_map
from .source_catalog import security_snapshot_source_rows
from .supabase_writer import SupabaseWriter


class SnapshotProvider(Protocol):
    def fetch(self, dataset: str) -> ProviderPayload: ...


class SnapshotWriter(Protocol):
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
class SecuritySnapshotImporter:
    """Import one profile-confirmed session; never infer historical intervals."""

    def __init__(
        self,
        *,
        settings: ApiProviderSettings,
        registry: Mapping[str, SnapshotProvider] | None = None,
        writer: SnapshotWriter | None = None,
    ) -> None:
        self.settings = settings
        provider_registry = registry or cast(
            Mapping[str, SnapshotProvider],
            build_provider_registry(settings),
        )
        self.registry = dict(provider_registry)
        self.writer = writer

    def _writer(self) -> SnapshotWriter:
        if self.writer is None:
            self.writer = SupabaseWriter(
                url=self.settings.supabase_url,
                server_key=self.settings.supabase_service_role_key,
                timeout=max(self.settings.timeout_seconds, 30.0),
            )
        return self.writer

    def _fetch_all(self, markets: Sequence[str]) -> dict[str, ProviderPayload]:
        mops = self.registry["MOPS"]
        requests: dict[str, PayloadFetchRequest] = {}
        if "TWSE" in markets:
            twse = self.registry["TWSE"]
            requests.update(
                {
                    "mops_listed_profiles": PayloadFetchRequest(
                        "MOPS", mops, "listed_company_profile"
                    ),
                    "twse_restrictions": PayloadFetchRequest("TWSE", twse, "changed_trading"),
                    "twse_suspended": PayloadFetchRequest("TWSE", twse, "suspended"),
                    "twse_attention": PayloadFetchRequest("TWSE", twse, "attention"),
                    "twse_disposals": PayloadFetchRequest("TWSE", twse, "disposals"),
                }
            )
        if "TPEX" in markets:
            tpex = self.registry["TPEX"]
            requests.update(
                {
                    "mops_otc_profiles": PayloadFetchRequest("MOPS", mops, "otc_company_profile"),
                    "tpex_restrictions": PayloadFetchRequest("TPEX", tpex, "trading_restrictions"),
                    "tpex_suspended": PayloadFetchRequest("TPEX", tpex, "suspended_history"),
                    "tpex_attention": PayloadFetchRequest("TPEX", tpex, "attention"),
                    "tpex_disposals": PayloadFetchRequest("TPEX", tpex, "disposals"),
                }
            )
        return fetch_provider_payloads(requests)

    @staticmethod
    def _bundles(
        payloads: Mapping[str, ProviderPayload],
    ) -> dict[str, MarketSnapshotPayloads]:
        bundles: dict[str, MarketSnapshotPayloads] = {}
        if "mops_listed_profiles" in payloads:
            bundles["TWSE"] = MarketSnapshotPayloads(
                profile=payloads["mops_listed_profiles"],
                restrictions=payloads["twse_restrictions"],
                suspended=payloads["twse_suspended"],
                attention=payloads["twse_attention"],
                disposals=payloads["twse_disposals"],
            )
        if "mops_otc_profiles" in payloads:
            bundles["TPEX"] = MarketSnapshotPayloads(
                profile=payloads["mops_otc_profiles"],
                restrictions=payloads["tpex_restrictions"],
                suspended=payloads["tpex_suspended"],
                attention=payloads["tpex_attention"],
                disposals=payloads["tpex_disposals"],
            )
        return bundles

    def run(
        self,
        *,
        snapshot_date: date | None,
        dry_run: bool = False,
        market: str | None = None,
    ) -> SecuritySnapshotSummary:
        normalized_market = market.strip().upper() if market is not None else None
        if normalized_market is not None and normalized_market not in {
            "TWSE",
            "TPEX",
        }:
            raise ValueError("market must be TWSE or TPEX")
        markets = ("TWSE", "TPEX") if normalized_market is None else (normalized_market,)
        payloads = self._fetch_all(markets)
        bundles = self._bundles(payloads)
        if set(bundles) != set(markets):
            raise IngestionError(
                "SECURITY_SNAPSHOT_MARKETS_INCOMPLETE",
                "Every selected market must have one complete source bundle",
            )
        snapshot_date = snapshot_date or (
            resolve_coherent_profile_date(bundles)
            if len(markets) == 2
            else resolve_market_profile_date(
                bundles[markets[0]],
                market=markets[0],
            )
        )
        required_sources = {
            "MOPS",
            *markets,
            *(f"{selected_market}_MOPS_SNAPSHOT" for selected_market in markets),
        }
        source_rows = [
            row
            for row in [*data_source_rows(), *security_snapshot_source_rows()]
            if row["source_code"] in required_sources
        ]
        provisional_sources = {
            "MOPS": 1,
            "TWSE_MOPS_SNAPSHOT": 4,
            "TPEX_MOPS_SNAPSHOT": 5,
        }
        profile_dataset = {
            "TWSE": "mops_listed_profiles",
            "TPEX": "mops_otc_profiles",
        }
        profiles: dict[str, list[dict[str, object]]] = {}
        excluded_profiles: dict[str, int] = {}
        for selected_market in markets:
            rows, excluded = normalize_company_profiles(
                payloads[profile_dataset[selected_market]],
                market=selected_market,
                source_id=provisional_sources["MOPS"],
            )
            profiles[selected_market] = rows
            excluded_profiles[selected_market] = excluded
        if any(
            len(profiles[selected_market]) < MIN_SECURITIES_PER_MARKET
            for selected_market in markets
        ):
            raise IngestionError(
                "SECURITY_MASTER_COVERAGE_TOO_LOW",
                "Current security snapshot is below the minimum market coverage",
            )
        securities = [row for selected_market in markets for row in profiles[selected_market]]
        provisional_security_ids = {
            (str(row["market"]), str(row["symbol"])): index
            for index, row in enumerate(securities, start=1)
        }
        normalized = {
            market: normalize_current_security_snapshot(
                bundle,
                market=market,
                snapshot_date=snapshot_date,
                source_id=provisional_sources[f"{market}_MOPS_SNAPSHOT"],
                security_ids=provisional_security_ids,
            )
            for market, bundle in bundles.items()
        }
        if any(
            len(normalized[selected_market].rows) != len(profiles[selected_market])
            for selected_market in markets
        ):
            raise IngestionError(
                "SECURITY_SNAPSHOT_IDENTITY_INCOMPLETE",
                "A normalized company profile could not be resolved to one security",
            )

        profile_dates_match_snapshot = all(
            item.profile_date == snapshot_date for item in normalized.values()
        )
        if not dry_run and not profile_dates_match_snapshot:
            raise IngestionError(
                "SECURITY_SNAPSHOT_NOT_TRADING_DAY",
                "Every selected market profile must confirm the snapshot date before a write",
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
            if set(source_ids) != required_sources:
                raise IngestionError(
                    "DATA_SOURCE_UPSERT_INCOMPLETE",
                    "Supabase did not return every security snapshot data source",
                )
            securities = [{**row, "source_id": source_ids["MOPS"]} for row in securities]
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
            normalized = {
                market: normalize_current_security_snapshot(
                    bundle,
                    market=market,
                    snapshot_date=snapshot_date,
                    source_id=source_ids[f"{market}_MOPS_SNAPSHOT"],
                    security_ids=security_ids,
                )
                for market, bundle in bundles.items()
            }
            history_rows = [
                row for selected_market in markets for row in normalized[selected_market].rows
            ]
            _ = self._writer().upsert(
                "security_history",
                history_rows,
                on_conflict="security_id,effective_from,source_id,source_version",
                preserve_existing=True,
            )
            self._writer().refresh_home_data_status()

        database_counts = (
            {}
            if dry_run
            else {
                table: self._writer().count_rows(table)
                for table in ("data_sources", "securities", "security_history")
            }
        )
        latest_available_at = max(item.retrieved_at for item in payloads.values())
        return SecuritySnapshotSummary(
            snapshot_date=snapshot_date,
            dry_run=dry_run,
            markets=markets,
            fetched_records={
                name: int(payload.record_count or 0) for name, payload in payloads.items()
            },
            normalized_records={
                "data_sources": len(source_rows),
                "securities": len(securities),
                "security_history": sum(len(item.rows) for item in normalized.values()),
            },
            excluded_records={
                "listed_profiles": excluded_profiles.get("TWSE", 0),
                "otc_profiles": excluded_profiles.get("TPEX", 0),
                "twse_intraday_suspensions": (
                    normalized["TWSE"].excluded_intraday_suspensions if "TWSE" in normalized else 0
                ),
                "tpex_intraday_suspensions": (
                    normalized["TPEX"].excluded_intraday_suspensions if "TPEX" in normalized else 0
                ),
            },
            database_counts=database_counts,
            source_versions={
                **{name: revision_version(payload) for name, payload in payloads.items()},
                **{
                    f"{market.lower()}_bundle_hash": snapshot_revision_hash(bundle)
                    for market, bundle in bundles.items()
                },
            },
            source_dates={
                market: item.profile_date.isoformat() for market, item in normalized.items()
            },
            latest_available_at=latest_available_at,
            reason_codes=(
                SECURITY_SNAPSHOT_REASON_CODES
                if profile_dates_match_snapshot
                else (
                    *SECURITY_SNAPSHOT_REASON_CODES,
                    (NON_SESSION_REASON if len(markets) == 2 else MARKET_NON_SESSION_REASON),
                )
            ),
        )
