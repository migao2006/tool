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
from .quality import MIN_SECURITIES_PER_MARKET
from .security_snapshot import (
    normalize_current_security_snapshot,
    snapshot_revision_hash,
)
from .security_snapshot_contracts import (
    MarketSnapshotPayloads,
    NON_SESSION_REASON,
    SECURITY_SNAPSHOT_REASON_CODES,
    SecuritySnapshotSummary,
)
from .security_snapshot_ids import returned_id_map, returned_security_id_map
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


@final
class SecuritySnapshotImporter:
    """Import one retrieval-day snapshot; never infer historical intervals."""

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

    def _fetch_all(self) -> dict[str, ProviderPayload]:
        mops, twse, tpex = (
            self.registry["MOPS"],
            self.registry["TWSE"],
            self.registry["TPEX"],
        )
        return {
            "mops_listed_profiles": mops.fetch("listed_company_profile"),
            "mops_otc_profiles": mops.fetch("otc_company_profile"),
            "twse_restrictions": twse.fetch("changed_trading"),
            "twse_suspended": twse.fetch("suspended"),
            "twse_attention": twse.fetch("attention"),
            "twse_disposals": twse.fetch("disposals"),
            "tpex_restrictions": tpex.fetch("trading_restrictions"),
            "tpex_suspended": tpex.fetch("suspended_history"),
            "tpex_attention": tpex.fetch("attention"),
            "tpex_disposals": tpex.fetch("disposals"),
        }

    @staticmethod
    def _bundles(
        payloads: Mapping[str, ProviderPayload],
    ) -> dict[str, MarketSnapshotPayloads]:
        return {
            "TWSE": MarketSnapshotPayloads(
                profile=payloads["mops_listed_profiles"],
                restrictions=payloads["twse_restrictions"],
                suspended=payloads["twse_suspended"],
                attention=payloads["twse_attention"],
                disposals=payloads["twse_disposals"],
            ),
            "TPEX": MarketSnapshotPayloads(
                profile=payloads["mops_otc_profiles"],
                restrictions=payloads["tpex_restrictions"],
                suspended=payloads["tpex_suspended"],
                attention=payloads["tpex_attention"],
                disposals=payloads["tpex_disposals"],
            ),
        }

    def run(
        self,
        *,
        snapshot_date: date,
        dry_run: bool = False,
    ) -> SecuritySnapshotSummary:
        payloads = self._fetch_all()
        bundles = self._bundles(payloads)
        source_rows = [*data_source_rows(), *security_snapshot_source_rows()]
        provisional_sources = {
            "MOPS": 1,
            "TWSE_MOPS_SNAPSHOT": 4,
            "TPEX_MOPS_SNAPSHOT": 5,
        }
        listed, excluded_listed = normalize_company_profiles(
            payloads["mops_listed_profiles"], market="TWSE", source_id=1
        )
        otc, excluded_otc = normalize_company_profiles(
            payloads["mops_otc_profiles"], market="TPEX", source_id=1
        )
        if min(len(listed), len(otc)) < MIN_SECURITIES_PER_MARKET:
            raise IngestionError(
                "SECURITY_MASTER_COVERAGE_TOO_LOW",
                "Current security snapshot is below the minimum market coverage",
            )
        securities = [*listed, *otc]
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
        if len(normalized["TWSE"].rows) != len(listed) or len(
            normalized["TPEX"].rows
        ) != len(otc):
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
                "Both market profiles must confirm the snapshot date before a write",
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
            required_sources = {
                "MOPS",
                "TWSE",
                "TPEX",
                "TWSE_MOPS_SNAPSHOT",
                "TPEX_MOPS_SNAPSHOT",
            }
            if set(source_ids) != required_sources:
                raise IngestionError(
                    "DATA_SOURCE_UPSERT_INCOMPLETE",
                    "Supabase did not return every security snapshot data source",
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
                *normalized["TWSE"].rows,
                *normalized["TPEX"].rows,
            ]
            _ = self._writer().upsert(
                "security_history",
                history_rows,
                on_conflict="security_id,effective_from,source_id,source_version",
                preserve_existing=True,
            )

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
            fetched_records={
                name: int(payload.record_count or 0)
                for name, payload in payloads.items()
            },
            normalized_records={
                "data_sources": len(source_rows),
                "securities": len(securities),
                "security_history": sum(
                    len(item.rows) for item in normalized.values()
                ),
            },
            excluded_records={
                "listed_profiles": excluded_listed,
                "otc_profiles": excluded_otc,
                "twse_intraday_suspensions": normalized[
                    "TWSE"
                ].excluded_intraday_suspensions,
                "tpex_intraday_suspensions": normalized[
                    "TPEX"
                ].excluded_intraday_suspensions,
            },
            database_counts=database_counts,
            source_versions={
                **{
                    name: revision_version(payload)
                    for name, payload in payloads.items()
                },
                **{
                    f"{market.lower()}_bundle_hash": snapshot_revision_hash(bundle)
                    for market, bundle in bundles.items()
                },
            },
            source_dates={
                market: item.profile_date.isoformat()
                for market, item in normalized.items()
            },
            latest_available_at=latest_available_at,
            reason_codes=(
                SECURITY_SNAPSHOT_REASON_CODES
                if profile_dates_match_snapshot
                else (*SECURITY_SNAPSHOT_REASON_CODES, NON_SESSION_REASON)
            ),
        )
