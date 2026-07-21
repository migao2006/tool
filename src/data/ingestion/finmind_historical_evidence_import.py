"""Bounded FinMind importer for TWSE historical action/state evidence."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from math import isfinite
from time import sleep
from typing import Protocol, final

from src.data.providers.finmind import FinMindClient
from src.data.providers.settings import ApiProviderSettings

from .contracts import IngestionError
from .finmind_historical_evidence_batch import (
    GLOBAL_DATASETS,
    FinMindHistoricalEvidenceProvider,
    datasets_for_scope,
    fetch_evidence_payloads,
    normalize_evidence_payloads,
    quota_remaining,
)
from .finmind_historical_evidence_contracts import (
    FinMindHistoricalEvidenceImportSummary,
    HistoricalEvidenceIdentity,
)
from .finmind_historical_evidence_rows import validate_twse_common_symbols
from .finmind_historical_identity import (
    load_verified_twse_identities,
    positive_database_id,
)
from .source_catalog import finmind_data_source_row
from .supabase_writer import SupabaseWriter


MAX_SYMBOLS = 20


class FinMindHistoricalEvidenceWriter(Protocol):
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


@final
class FinMindHistoricalEvidenceImporter:
    """Fetch first, then append action evidence without PIT promotion."""

    def __init__(
        self,
        *,
        settings: ApiProviderSettings,
        provider: FinMindHistoricalEvidenceProvider | None = None,
        writer: FinMindHistoricalEvidenceWriter | None = None,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        self.settings = settings
        self.provider = provider or FinMindClient(token=settings.finmind_token)
        self.writer = writer
        self._sleep = sleep_fn

    def _writer(self) -> FinMindHistoricalEvidenceWriter:
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
        scope: str = "ALL",
        quota_reserve: int = 0,
        dry_run: bool = False,
        identities: Sequence[HistoricalEvidenceIdentity] | None = None,
        global_symbols: Sequence[str] | None = None,
    ) -> FinMindHistoricalEvidenceImportSummary:
        requested = validate_twse_common_symbols(symbols)
        normalized_scope = scope.strip().upper()
        expected_datasets = datasets_for_scope(normalized_scope)
        if global_symbols is not None and not set(GLOBAL_DATASETS) & expected_datasets:
            raise IngestionError(
                "FINMIND_HISTORICAL_GLOBAL_SYMBOLS_UNEXPECTED",
                "global_symbols may only be used when global datasets are requested",
            )
        requested_global = (
            validate_twse_common_symbols(global_symbols or requested)
            if set(GLOBAL_DATASETS) & expected_datasets
            else ()
        )
        if normalized_scope != "GLOBAL" and len(requested) > MAX_SYMBOLS:
            raise IngestionError(
                "FINMIND_HISTORICAL_SYMBOL_LIMIT",
                f"at most {MAX_SYMBOLS} symbols may be imported at once",
            )
        if end_date < start_date:
            raise IngestionError(
                "FINMIND_HISTORICAL_DATE_RANGE_INVALID",
                "start_date must not be after end_date",
            )
        if not isfinite(pacing_seconds) or not 0 <= pacing_seconds <= 60:
            raise IngestionError(
                "FINMIND_HISTORICAL_PACING_INVALID",
                "pacing_seconds must be between 0 and 60",
            )
        if isinstance(quota_reserve, bool) or not 0 <= quota_reserve <= 10_000:
            raise IngestionError(
                "FINMIND_HISTORICAL_QUOTA_RESERVE_INVALID",
                "quota_reserve must be an integer between 0 and 10000",
            )
        required_requests = (
            len(requested) if "dividend_results" in expected_datasets else 0
        ) + sum(dataset in expected_datasets for dataset in GLOBAL_DATASETS)
        if (
            quota_remaining(self.provider.fetch_quota())
            < required_requests + quota_reserve
        ):
            raise IngestionError(
                "FINMIND_HISTORICAL_QUOTA_INSUFFICIENT",
                "FinMind quota is insufficient for the bounded evidence import",
            )

        payloads = fetch_evidence_payloads(
            self.provider,
            symbols=requested,
            start_date=start_date,
            end_date=end_date,
            pacing_seconds=pacing_seconds,
            scope=normalized_scope,
            sleep_fn=self._sleep,
        )
        identity_symbols = tuple(dict.fromkeys((*requested, *requested_global)))
        active_identities = tuple(
            identities
            if identities is not None
            else ()
            if dry_run
            else load_verified_twse_identities(self._writer(), symbols=identity_symbols)
        )
        normalized = normalize_evidence_payloads(
            payloads,
            source_id=1,
            dividend_symbols=requested,
            global_symbols=requested_global,
            start_date=start_date,
            end_date=end_date,
            identities=active_identities,
        )

        submitted = 0
        if not dry_run:
            returned_sources = self._writer().upsert(
                "data_sources",
                [finmind_data_source_row()],
                on_conflict="source_code",
                select="source_id,source_code",
                return_rows=True,
            )
            matching = [
                row for row in returned_sources if row.get("source_code") == "FINMIND"
            ]
            if len(matching) != 1:
                raise IngestionError(
                    "DATA_SOURCE_UPSERT_INCOMPLETE",
                    "Supabase did not return the FinMind data source",
                )
            source_id = positive_database_id(matching[0].get("source_id"), "source_id")
            normalized = normalize_evidence_payloads(
                payloads,
                source_id=source_id,
                dividend_symbols=requested,
                global_symbols=requested_global,
                start_date=start_date,
                end_date=end_date,
                identities=active_identities,
            )
            if normalized.action_rows:
                _ = self._writer().upsert(
                    "historical_corporate_action_observations",
                    normalized.action_rows,
                    on_conflict=(
                        "source_id,source_dataset,source_event_id,action_type,"
                        "source_revision_hash"
                    ),
                    preserve_existing=True,
                )
                submitted = len(normalized.action_rows)

        all_rows = (*normalized.action_rows, *normalized.state_event_rows)
        identity_counts = Counter(
            str(row["identity_resolution_status"]) for row in all_rows
        )
        fetched: Counter[str] = Counter()
        for payload in payloads:
            fetched[payload.dataset] += int(payload.record_count or 0)
        database_counts = (
            {}
            if dry_run
            else {
                "historical_corporate_action_observations": self._writer().count_rows(
                    "historical_corporate_action_observations"
                )
            }
        )
        return FinMindHistoricalEvidenceImportSummary(
            dry_run=dry_run,
            import_scope=normalized_scope,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            requested_symbols=requested,
            requested_global_symbols=requested_global,
            fetched_records=dict(fetched),
            normalized_action_rows=len(normalized.action_rows),
            canonical_state_event_rows=len(normalized.state_event_rows),
            excluded_rows=normalized.excluded_rows,
            verified_identity_rows=identity_counts["VERIFIED"],
            unresolved_identity_rows=(
                identity_counts["UNRESOLVED"] + identity_counts["CONFLICT"]
            ),
            action_rows_submitted=submitted,
            state_event_rows_persisted=0,
            source_payload_hashes=tuple(payload.payload_sha256 for payload in payloads),
            source_retrieved_at=tuple(
                payload.retrieved_at.isoformat() for payload in payloads
            ),
            database_counts=database_counts,
        )
