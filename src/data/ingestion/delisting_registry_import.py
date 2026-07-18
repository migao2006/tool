"""Fetch-first importer for unresolved official delisting observations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol, cast, final
from zoneinfo import ZoneInfo

from src.data.providers.contracts import ProviderPayload
from src.data.providers.registry import build_provider_registry
from src.data.providers.settings import ApiProviderSettings

from .contracts import IngestionError
from .delisting_registry import normalize_delisting_registry
from .delisting_registry_contracts import (
    DELISTING_REASON_CODES,
    DelistingRegistrySummary,
    NormalizedDelistingRegistry,
)
from .normalizers import data_source_rows, revision_version
from .returned_ids import returned_id_map
from .supabase_writer import SupabaseWriter


TAIPEI = ZoneInfo("Asia/Taipei")
MIN_DELISTING_ROWS = {"TWSE": 200, "TPEX": 500}
SNAPSHOT_DATE_MISMATCH = "SNAPSHOT_DATE_DOES_NOT_MATCH_RETRIEVAL_DATE"


class DelistingProvider(Protocol):
    def fetch(self, dataset: str) -> ProviderPayload: ...


class DelistingWriter(Protocol):
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
class DelistingRegistryImporter:
    """Persist source events without touching securities or security_history."""

    def __init__(
        self,
        *,
        settings: ApiProviderSettings,
        registry: Mapping[str, DelistingProvider] | None = None,
        writer: DelistingWriter | None = None,
    ) -> None:
        self.settings = settings
        providers = registry or cast(
            Mapping[str, DelistingProvider],
            build_provider_registry(settings),
        )
        self.registry = dict(providers)
        self.writer = writer

    def _writer(self) -> DelistingWriter:
        if self.writer is None:
            self.writer = SupabaseWriter(
                url=self.settings.supabase_url,
                server_key=self.settings.supabase_service_role_key,
                timeout=max(self.settings.timeout_seconds, 30.0),
            )
        return self.writer

    def _fetch_all(self) -> dict[str, ProviderPayload]:
        return {
            market: self.registry[market].fetch("delisting_registry")
            for market in ("TWSE", "TPEX")
        }

    @staticmethod
    def _normalize(
        payloads: Mapping[str, ProviderPayload],
        *,
        source_ids: Mapping[str, int],
    ) -> dict[str, NormalizedDelistingRegistry]:
        normalized = {
            market: normalize_delisting_registry(
                payloads[market],
                market=market,
                source_id=source_ids[market],
            )
            for market in ("TWSE", "TPEX")
        }
        for market, result in normalized.items():
            if len(result.rows) < MIN_DELISTING_ROWS[market]:
                raise IngestionError(
                    "DELISTING_COVERAGE_TOO_LOW",
                    f"{market} delisting registry is below the verified coverage floor",
                )
        return normalized

    def run(
        self,
        *,
        snapshot_date: date,
        dry_run: bool = False,
    ) -> DelistingRegistrySummary:
        payloads = self._fetch_all()
        source_rows = [
            row
            for row in data_source_rows()
            if str(row["source_code"]) in {"TWSE", "TPEX"}
        ]
        normalized = self._normalize(
            payloads,
            source_ids={"TWSE": 1, "TPEX": 2},
        )
        retrieval_dates = {
            market: payload.retrieved_at.astimezone(TAIPEI).date()
            for market, payload in payloads.items()
        }
        retrieval_date_matches = all(
            value == snapshot_date for value in retrieval_dates.values()
        )
        if not dry_run and not retrieval_date_matches:
            raise IngestionError(
                "DELISTING_SNAPSHOT_DATE_INVALID",
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
                returned_sources,
                code_key="source_code",
                id_key="source_id",
            )
            if set(source_ids) != {"TWSE", "TPEX"}:
                raise IngestionError(
                    "DATA_SOURCE_UPSERT_INCOMPLETE",
                    "Supabase did not return both delisting registry sources",
                )
            normalized = self._normalize(payloads, source_ids=source_ids)
            rows = [
                row for market in ("TWSE", "TPEX") for row in normalized[market].rows
            ]
            _ = self._writer().upsert(
                "delisting_registry_observations",
                rows,
                on_conflict=(
                    "source_id,source_dataset,source_event_id,source_revision_hash"
                ),
                preserve_existing=True,
            )

        database_counts = (
            {}
            if dry_run
            else {
                table: self._writer().count_rows(table)
                for table in ("data_sources", "delisting_registry_observations")
            }
        )
        return DelistingRegistrySummary(
            snapshot_date=snapshot_date,
            dry_run=dry_run,
            fetched_records={
                market: len(normalized[market].rows) for market in ("TWSE", "TPEX")
            },
            normalized_records={
                market: len(normalized[market].rows) for market in ("TWSE", "TPEX")
            },
            database_counts=database_counts,
            source_versions={
                market: revision_version(payload)
                for market, payload in payloads.items()
            },
            source_dates={
                **{
                    f"{market.lower()}_retrieved": observed.isoformat()
                    for market, observed in retrieval_dates.items()
                },
                **{
                    f"{market.lower()}_termination_min": (
                        normalized[market].termination_date_min.isoformat()
                    )
                    for market in ("TWSE", "TPEX")
                },
                **{
                    f"{market.lower()}_termination_max": (
                        normalized[market].termination_date_max.isoformat()
                    )
                    for market in ("TWSE", "TPEX")
                },
            },
            latest_available_at=max(
                payload.retrieved_at for payload in payloads.values()
            ),
            reason_codes=(
                DELISTING_REASON_CODES
                if retrieval_date_matches
                else (*DELISTING_REASON_CODES, SNAPSHOT_DATE_MISMATCH)
            ),
        )
