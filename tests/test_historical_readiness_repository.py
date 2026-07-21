from __future__ import annotations

from collections.abc import Mapping
from typing import final

from src.data.ingestion.contracts import IngestionError
from src.quality.historical_readiness_repository import HistoricalReadinessRepository


@final
class FakeCounter:
    def __init__(
        self,
        *,
        fail_listing: bool = False,
        fail_canonical_contract: bool = False,
    ) -> None:
        self.fail_listing = fail_listing
        self.fail_canonical_contract = fail_canonical_contract
        self.calls: list[tuple[str, Mapping[str, str] | None]] = []

    def count_rows(
        self,
        table: str,
        *,
        filters: Mapping[str, str] | None = None,
    ) -> int:
        self.calls.append((table, filters))
        if self.fail_listing and table == "security_listing_periods":
            raise IngestionError("SUPABASE_WRITE_REJECTED", "table is unavailable")
        if self.fail_canonical_contract and table == "canonical_dataset_objects":
            raise IngestionError("SUPABASE_WRITE_REJECTED", "table is unavailable")
        return {
            "security_listing_periods": 500,
            "trading_calendar_observations": 1_300,
            "security_state_snapshots": 25,
            "company_action_coverage_observations": 1_700,
            "delisting_registry_observations": 843,
            "canonical_dataset_objects": 0,
        }[table]

    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]:
        del select, limit
        self.calls.append((table, filters))
        rows: dict[str, list[dict[str, object]]] = {
            "security_state_snapshots": [
                {
                    "security_state_snapshot_id": 1,
                    "fully_observed_row_count": 25,
                }
            ],
            "canonical_dataset_objects": [
                {"canonical_object_id": 1, "model_eligible_row_count": 0}
            ],
        }
        return rows[table]


def _manifest(symbol: str, market: str) -> dict[str, object]:
    return {
        "source_symbol": symbol,
        "scheduled_market": market,
        "asset_type": "COMMON_STOCK",
    }


def test_repository_counts_persisted_evidence_and_keeps_intersections_locked() -> None:
    source = FakeCounter()

    metrics = HistoricalReadinessRepository(source).collect(
        archive_integrity_status="PASS",
        archive_object_count=3,
        archive_row_count=100,
        manifest_rows=(
            _manifest("2330", "TWSE"),
            _manifest("2330", "TWSE"),
            _manifest("6488", "TPEX"),
        ),
    )

    assert metrics.twse_archive_symbol_count == 1
    assert metrics.tpex_archive_symbol_count == 1
    assert metrics.twse_pit_covered_archive_symbol_count == 0
    assert metrics.tpex_pit_covered_archive_symbol_count == 0
    assert metrics.pit_covered_trading_session_count == 0
    assert metrics.verified_security_state_count == 25
    assert metrics.verified_company_action_coverage_count == 1_700
    assert metrics.canonical_contract_object_count == 0
    assert metrics.canonical_production_row_count == 0
    assert metrics.unresolved_delisting_count == 843
    listing_filters = source.calls[0][1]
    assert listing_filters is not None
    assert listing_filters["usage_scope"] == "eq.POINT_IN_TIME_IDENTITY"
    state_call = next(call for call in source.calls if call[0] == "security_state_snapshots")
    assert state_call[1] is not None
    assert state_call[1]["unknown_state_row_count"] == "eq.0"
    canonical_calls = [
        call for call in source.calls if call[0] == "canonical_dataset_objects"
    ]
    assert len(canonical_calls) == 2
    contract_call = canonical_calls[0]
    assert contract_call[1] == {
        "asset_type": "eq.COMMON_STOCK",
        "horizon": "eq.5",
    }
    aggregate_call = canonical_calls[1]
    assert aggregate_call[1] is not None
    assert aggregate_call[1]["order"] == "canonical_object_id.asc"


def test_missing_new_schema_is_explicitly_unavailable() -> None:
    metrics = HistoricalReadinessRepository(FakeCounter(fail_listing=True)).collect(
        archive_integrity_status="PASS",
        archive_object_count=1,
        archive_row_count=1,
        manifest_rows=(_manifest("2330", "TWSE"),),
    )

    assert metrics.twse_verified_listing_period_count is None
    assert metrics.tpex_verified_listing_period_count is None
    assert metrics.conflicting_listing_period_count is None


def test_unreadable_canonical_contract_is_explicitly_unavailable() -> None:
    metrics = HistoricalReadinessRepository(
        FakeCounter(fail_canonical_contract=True)
    ).collect(
        archive_integrity_status="PASS",
        archive_object_count=1,
        archive_row_count=1,
        manifest_rows=(_manifest("2330", "TWSE"),),
    )

    assert metrics.canonical_contract_object_count is None
    assert metrics.canonical_production_row_count == 0
