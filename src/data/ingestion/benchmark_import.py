"""Fetch-first importer for official current-month total-return benchmarks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol, cast, final
from zoneinfo import ZoneInfo

from src.data.providers.contracts import ProviderPayload
from src.data.providers.registry import build_provider_registry
from src.data.providers.settings import ApiProviderSettings

from .benchmark_contracts import (
    BENCHMARK_REASON_CODES,
    BenchmarkImportSummary,
)
from .benchmark_definitions import benchmark_definition_rows
from .benchmark_observations import normalize_total_return_index
from .contracts import IngestionError
from .normalizers import data_source_rows, revision_version
from .parallel_fetch import PayloadFetchRequest, fetch_provider_payloads
from .returned_ids import returned_id_map
from .supabase_writer import SupabaseWriter


TAIPEI = ZoneInfo("Asia/Taipei")
SNAPSHOT_DATE_MISMATCH = "SNAPSHOT_DATE_DOES_NOT_MATCH_RETRIEVAL_DATE"


class BenchmarkProvider(Protocol):
    def fetch(self, dataset: str) -> ProviderPayload: ...


class BenchmarkWriter(Protocol):
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

    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]: ...

    def count_rows(self, table: str) -> int: ...

    def refresh_home_data_status(self) -> None: ...


@final
class BenchmarkImporter:
    """Store official closes while keeping the execution mismatch explicit."""

    def __init__(
        self,
        *,
        settings: ApiProviderSettings,
        registry: Mapping[str, BenchmarkProvider] | None = None,
        writer: BenchmarkWriter | None = None,
    ) -> None:
        self.settings = settings
        providers = registry or cast(
            Mapping[str, BenchmarkProvider],
            build_provider_registry(settings),
        )
        self.registry = dict(providers)
        self.writer = writer

    def _writer(self) -> BenchmarkWriter:
        if self.writer is None:
            self.writer = SupabaseWriter(
                url=self.settings.supabase_url,
                server_key=self.settings.supabase_service_role_key,
                timeout=max(self.settings.timeout_seconds, 30.0),
            )
        return self.writer

    def _fetch_all(self) -> dict[str, ProviderPayload]:
        return fetch_provider_payloads(
            {
                market: PayloadFetchRequest(
                    market, self.registry[market], "return_index"
                )
                for market in ("TWSE", "TPEX")
            }
        )

    @staticmethod
    def _normalize(
        payloads: Mapping[str, ProviderPayload],
        *,
        source_ids: Mapping[str, int],
    ) -> dict[str, list[dict[str, object]]]:
        return {
            market: normalize_total_return_index(
                payloads[market],
                market=market,
                source_id=source_ids[market],
            )
            for market in ("TWSE", "TPEX")
        }

    @staticmethod
    def _latest_session_dates(
        observations: Mapping[str, Sequence[Mapping[str, object]]],
    ) -> dict[str, date]:
        latest: dict[str, date] = {}
        for market in ("TWSE", "TPEX"):
            rows = observations[market]
            if not rows:
                raise IngestionError(
                    "BENCHMARK_COVERAGE_EMPTY",
                    f"{market} total-return index did not return observations",
                )
            latest[market] = max(
                date.fromisoformat(str(row["observation_at"])[:10]) for row in rows
            )
        if len(set(latest.values())) != 1:
            raise IngestionError(
                "BENCHMARK_MARKET_DATES_MISMATCH",
                "TWSE and TPEx total-return indexes end on different sessions",
            )
        return latest

    def run(
        self,
        *,
        snapshot_date: date,
        dry_run: bool = False,
    ) -> BenchmarkImportSummary:
        payloads = self._fetch_all()
        source_rows = [
            row
            for row in data_source_rows()
            if str(row["source_code"]) in {"TWSE", "TPEX"}
        ]
        provisional_source_ids = {"TWSE": 1, "TPEX": 2}
        observations = self._normalize(
            payloads, source_ids=provisional_source_ids
        )
        latest_sessions = self._latest_session_dates(observations)
        if any(value > snapshot_date for value in latest_sessions.values()):
            raise IngestionError(
                "BENCHMARK_FUTURE_SESSION",
                "Benchmark response contains a session after the snapshot date",
            )
        definitions = benchmark_definition_rows(
            payloads=payloads,
            observations=observations,
            source_ids=provisional_source_ids,
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
                "BENCHMARK_SNAPSHOT_DATE_INVALID",
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
                    "Supabase did not return both benchmark sources",
                )
            observations = self._normalize(payloads, source_ids=source_ids)
            definitions = benchmark_definition_rows(
                payloads=payloads,
                observations=observations,
                source_ids=source_ids,
            )
            _ = self._writer().upsert(
                "benchmark_definitions",
                definitions,
                on_conflict="benchmark_code,benchmark_version",
                preserve_existing=True,
            )
            returned_definitions = self._writer().select_rows(
                "benchmark_definitions",
                select="benchmark_id,benchmark_code,benchmark_version",
                filters={
                    "benchmark_code": (
                        "in.(TWSE_TOTAL_RETURN_INDEX,TPEX_TOTAL_RETURN_INDEX)"
                    ),
                    "benchmark_version": "eq.official-total-return-close-v1",
                },
                limit=2,
            )
            benchmark_ids = returned_id_map(
                returned_definitions,
                code_key="benchmark_code",
                id_key="benchmark_id",
            )
            if set(benchmark_ids) != {
                "TWSE_TOTAL_RETURN_INDEX",
                "TPEX_TOTAL_RETURN_INDEX",
            }:
                raise IngestionError(
                    "BENCHMARK_DEFINITION_UPSERT_INCOMPLETE",
                    "Supabase did not return both benchmark definitions",
                )
            rows = [
                {
                    **row,
                    "benchmark_id": benchmark_ids[str(row["series_code"])],
                }
                for market in ("TWSE", "TPEX")
                for row in observations[market]
            ]
            _ = self._writer().upsert(
                "market_observations",
                rows,
                on_conflict=(
                    "series_code,observation_at,source_id,source_revision_hash"
                ),
                preserve_existing=True,
            )
            self._writer().refresh_home_data_status()

        database_counts = (
            {}
            if dry_run
            else {
                table: self._writer().count_rows(table)
                for table in (
                    "data_sources",
                    "benchmark_definitions",
                    "market_observations",
                )
            }
        )
        return BenchmarkImportSummary(
            snapshot_date=snapshot_date,
            dry_run=dry_run,
            fetched_records={
                market: int(payload.record_count or 0)
                for market, payload in payloads.items()
            },
            normalized_records={
                "benchmark_definitions": len(definitions),
                "market_observations": sum(
                    len(rows) for rows in observations.values()
                ),
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
                    f"{market.lower()}_latest_session": observed.isoformat()
                    for market, observed in latest_sessions.items()
                },
            },
            latest_available_at=max(
                payload.retrieved_at for payload in payloads.values()
            ),
            reason_codes=(
                BENCHMARK_REASON_CODES
                if retrieval_date_matches
                else (*BENCHMARK_REASON_CODES, SNAPSHOT_DATE_MISMATCH)
            ),
        )
