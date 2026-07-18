"""Collect exact Supabase counts for the historical dataset readiness gate."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, final

from src.data.ingestion.contracts import IngestionError

from .historical_dataset_readiness import HistoricalDatasetReadinessMetrics


class FilteredRowCounter(Protocol):
    def count_rows(
        self,
        table: str,
        *,
        filters: Mapping[str, str] | None = None,
    ) -> int: ...


@final
class HistoricalReadinessRepository:
    """Read exact counts; unavailable new contracts remain explicit ``None``."""

    def __init__(self, source: FilteredRowCounter) -> None:
        self._source = source

    def _count(
        self,
        table: str,
        *,
        filters: Mapping[str, str] | None = None,
    ) -> int | None:
        try:
            return self._source.count_rows(table, filters=filters)
        except IngestionError:
            return None

    def collect(
        self,
        *,
        archive_integrity_status: str,
        archive_object_count: int,
        archive_row_count: int,
        manifest_rows: tuple[Mapping[str, object], ...],
    ) -> HistoricalDatasetReadinessMetrics:
        twse_symbols = {
            row.get("source_symbol")
            for row in manifest_rows
            if row.get("scheduled_market") == "TWSE"
            and row.get("asset_type") == "COMMON_STOCK"
            and isinstance(row.get("source_symbol"), str)
        }
        tpex_symbols = {
            row.get("source_symbol")
            for row in manifest_rows
            if row.get("scheduled_market") == "TPEX"
            and row.get("asset_type") == "COMMON_STOCK"
            and isinstance(row.get("source_symbol"), str)
        }
        verified_identity = {
            "asset_type": "eq.COMMON_STOCK",
            "identity_resolution_status": "eq.VERIFIED",
            "usage_scope": "eq.POINT_IN_TIME_IDENTITY",
            "system_status": "eq.PASS",
        }
        verified_calendar = {
            "is_trading_day": "eq.true",
            "calendar_verification_status": "eq.VERIFIED",
            "usage_scope": "eq.POINT_IN_TIME_CALENDAR",
            "system_status": "eq.PASS",
        }
        return HistoricalDatasetReadinessMetrics(
            archive_integrity_status=archive_integrity_status,
            archive_object_count=archive_object_count,
            archive_row_count=archive_row_count,
            twse_archive_symbol_count=len(twse_symbols),
            tpex_archive_symbol_count=len(tpex_symbols),
            # These must be computed from canonical row-level intersections.
            # No persistence contract exists yet, so promotion stays locked.
            twse_pit_covered_archive_symbol_count=0,
            tpex_pit_covered_archive_symbol_count=0,
            pit_covered_trading_session_count=0,
            twse_verified_listing_period_count=self._count(
                "security_listing_periods",
                filters={**verified_identity, "listing_market": "eq.TWSE"},
            ),
            tpex_verified_listing_period_count=self._count(
                "security_listing_periods",
                filters={**verified_identity, "listing_market": "eq.TPEX"},
            ),
            conflicting_listing_period_count=self._count(
                "security_listing_periods",
                filters={"identity_resolution_status": "eq.CONFLICT"},
            ),
            twse_verified_calendar_session_count=self._count(
                "trading_calendar_observations",
                filters={**verified_calendar, "market": "eq.TWSE"},
            ),
            tpex_verified_calendar_session_count=self._count(
                "trading_calendar_observations",
                filters={**verified_calendar, "market": "eq.TPEX"},
            ),
            # No versioned state/coverage/canonical persistence contract exists yet.
            # Zero is deliberate and keeps promotion/model training locked.
            verified_security_state_count=0,
            verified_company_action_coverage_count=0,
            unresolved_delisting_count=self._count(
                "delisting_registry_observations",
                filters={"identity_resolution_status": "eq.UNRESOLVED"},
            ),
            canonical_production_row_count=0,
        )
