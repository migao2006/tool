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

    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]: ...


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

    def _sum(
        self,
        table: str,
        *,
        id_field: str,
        value_field: str,
        filters: Mapping[str, str] | None = None,
    ) -> int | None:
        total = 0
        last_id = 0
        try:
            while True:
                page = self._source.select_rows(
                    table,
                    select=f"{id_field},{value_field}",
                    filters={
                        **dict(filters or {}),
                        id_field: f"gt.{last_id}",
                        "order": f"{id_field}.asc",
                    },
                    limit=1_000,
                )
                if len(page) > 1_000:
                    raise IngestionError(
                        "HISTORICAL_READINESS_AGGREGATE_INVALID",
                        "Supabase returned too many aggregate rows",
                    )
                if not page:
                    return total
                for row in page:
                    row_id = row.get(id_field)
                    value = row.get(value_field)
                    if (
                        isinstance(row_id, bool)
                        or not isinstance(row_id, int)
                        or row_id <= last_id
                        or isinstance(value, bool)
                        or not isinstance(value, int)
                        or value < 0
                    ):
                        raise IngestionError(
                            "HISTORICAL_READINESS_AGGREGATE_INVALID",
                            "Supabase returned invalid aggregate evidence",
                        )
                    last_id = row_id
                    total += value
                if len(page) < 1_000:
                    return total
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
        verified_security_state = {
            "asset_type": "eq.COMMON_STOCK",
            "verification_status": "eq.VERIFIED",
            "usage_scope": "eq.POINT_IN_TIME_SECURITY_STATE",
            "system_status": "eq.PASS",
            "unknown_state_row_count": "eq.0",
        }
        verified_action_coverage = {
            "asset_type": "eq.COMMON_STOCK",
            "coverage_resolution_status": "eq.VERIFIED",
            "coverage_completeness": "eq.COMPLETE",
            "usage_scope": "eq.POINT_IN_TIME_ACTION_COVERAGE",
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
            verified_security_state_count=self._sum(
                "security_state_snapshots",
                id_field="security_state_snapshot_id",
                value_field="fully_observed_row_count",
                filters=verified_security_state,
            ),
            verified_company_action_coverage_count=self._count(
                "company_action_coverage_observations",
                filters=verified_action_coverage,
            ),
            unresolved_delisting_count=self._count(
                "delisting_registry_observations",
                filters={"identity_resolution_status": "eq.UNRESOLVED"},
            ),
            # Zero means the canonical contract is installed but no object has
            # been built yet.  ``None`` means the contract cannot be verified.
            canonical_contract_object_count=self._count(
                "canonical_dataset_objects",
                filters={
                    "asset_type": "eq.COMMON_STOCK",
                    "horizon": "eq.5",
                },
            ),
            # The first canonical manifest contract enforces each value to zero.
            # Summing the stored field distinguishes a missing table (None) from
            # an available, correctly locked research contract (zero).
            canonical_production_row_count=self._sum(
                "canonical_dataset_objects",
                id_field="canonical_object_id",
                value_field="model_eligible_row_count",
                filters={
                    "asset_type": "eq.COMMON_STOCK",
                    "horizon": "eq.5",
                },
            ),
        )
