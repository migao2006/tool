"""Fetch-first importer for unresolved current MOPS listing evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol, cast, final
from zoneinfo import ZoneInfo

from src.data.providers.contracts import ProviderPayload
from src.data.providers.registry import build_provider_registry
from src.data.providers.settings import ApiProviderSettings

from .contracts import IngestionError
from .normalizers import data_source_rows, revision_version
from .quality import MIN_SECURITIES_PER_MARKET
from .returned_ids import returned_id_map
from .supabase_writer import SupabaseWriter
from .twse_current_listing_identity import (
    normalize_twse_current_listing_identities,
)
from .twse_current_listing_identity_contracts import (
    TWSE_CURRENT_LISTING_IDENTITY_REASON_CODES,
    TwseCurrentListingIdentityImportSummary,
)


TAIPEI = ZoneInfo("Asia/Taipei")
SNAPSHOT_DATE_MISMATCH = "SNAPSHOT_DATE_DOES_NOT_MATCH_RETRIEVAL_DATE"


class CurrentListingIdentityProvider(Protocol):
    def fetch(self, dataset: str) -> ProviderPayload: ...


class CurrentListingIdentityWriter(Protocol):
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
class TwseCurrentListingIdentityImporter:
    """Append current official profiles without asserting historical identity."""

    def __init__(
        self,
        *,
        settings: ApiProviderSettings,
        registry: Mapping[str, CurrentListingIdentityProvider] | None = None,
        writer: CurrentListingIdentityWriter | None = None,
    ) -> None:
        self.settings = settings
        providers = registry or cast(
            Mapping[str, CurrentListingIdentityProvider],
            build_provider_registry(settings),
        )
        self.registry = dict(providers)
        self.writer = writer

    def _writer(self) -> CurrentListingIdentityWriter:
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
        snapshot_date: date,
        dry_run: bool = False,
    ) -> TwseCurrentListingIdentityImportSummary:
        payload = self.registry["MOPS"].fetch("listed_company_profile")
        normalized = normalize_twse_current_listing_identities(payload, source_id=1)
        if len(normalized.rows) < MIN_SECURITIES_PER_MARKET:
            raise IngestionError(
                "CURRENT_LISTING_IDENTITY_COVERAGE_TOO_LOW",
                "The MOPS TWSE listing snapshot is below the coverage floor",
            )

        retrieval_date = payload.retrieved_at.astimezone(TAIPEI).date()
        retrieval_date_matches = retrieval_date == snapshot_date
        if not dry_run and not retrieval_date_matches:
            raise IngestionError(
                "CURRENT_LISTING_IDENTITY_SNAPSHOT_DATE_INVALID",
                "Snapshot date must equal the MOPS retrieval date",
            )

        if not dry_run:
            mops_source = [
                row for row in data_source_rows() if row["source_code"] == "MOPS"
            ]
            returned_sources = self._writer().upsert(
                "data_sources",
                mops_source,
                on_conflict="source_code",
                select="source_id,source_code",
                return_rows=True,
            )
            source_ids = returned_id_map(
                returned_sources,
                code_key="source_code",
                id_key="source_id",
            )
            if set(source_ids) != {"MOPS"}:
                raise IngestionError(
                    "DATA_SOURCE_UPSERT_INCOMPLETE",
                    "Supabase did not return the MOPS data source",
                )
            normalized = normalize_twse_current_listing_identities(
                payload,
                source_id=source_ids["MOPS"],
            )
            _ = self._writer().upsert(
                "security_listing_periods",
                normalized.rows,
                on_conflict=(
                    "source_id,source_dataset,source_event_id,source_revision_hash"
                ),
                preserve_existing=True,
            )

        reason_codes = TWSE_CURRENT_LISTING_IDENTITY_REASON_CODES
        if not retrieval_date_matches:
            reason_codes = (*reason_codes, SNAPSHOT_DATE_MISMATCH)
        return TwseCurrentListingIdentityImportSummary(
            snapshot_date=snapshot_date,
            dry_run=dry_run,
            fetched_records=int(payload.record_count or 0),
            normalized_records=len(normalized.rows),
            excluded_non_common_stock_rows=(
                normalized.excluded_non_common_stock_rows
            ),
            registration_id_rows=normalized.registration_id_rows,
            database_count=(
                None
                if dry_run
                else self._writer().count_rows("security_listing_periods")
            ),
            listing_date_min=normalized.listing_date_min,
            listing_date_max=normalized.listing_date_max,
            source_version=revision_version(payload),
            source_hash=payload.payload_sha256,
            latest_available_at=payload.retrieved_at,
            reason_codes=reason_codes,
        )
