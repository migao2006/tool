from dataclasses import replace

from src.quality.historical_dataset_readiness import (
    HistoricalDatasetReadinessMetrics,
    HistoricalDatasetReadinessThresholds,
    assess_historical_dataset_readiness,
)


def _metrics() -> HistoricalDatasetReadinessMetrics:
    return HistoricalDatasetReadinessMetrics(
        archive_integrity_status="PASS",
        archive_object_count=500,
        archive_row_count=3_000_000,
        twse_archive_symbol_count=1_000,
        tpex_archive_symbol_count=700,
        twse_pit_covered_archive_symbol_count=1_000,
        tpex_pit_covered_archive_symbol_count=700,
        pit_covered_trading_session_count=1_300,
        twse_verified_listing_period_count=1_000,
        tpex_verified_listing_period_count=700,
        conflicting_listing_period_count=0,
        twse_verified_calendar_session_count=1_300,
        tpex_verified_calendar_session_count=1_300,
        verified_security_state_count=10_000,
        verified_company_action_coverage_count=1_700,
        unresolved_delisting_count=0,
        canonical_contract_object_count=1,
        canonical_production_row_count=2_000_000,
    )


def test_complete_evidence_can_unlock_dataset_build_but_not_model_pass() -> None:
    result = assess_historical_dataset_readiness(_metrics())

    assert result.canonicalization_ready is True
    assert result.canonicalization_status == "READY_FOR_CANONICALIZATION"
    assert result.dataset_build_ready is True
    assert result.readiness_status == "READY_FOR_DATASET_BUILD"
    assert result.system_status == "RESEARCH_ONLY"
    assert result.reason_codes == ()


def test_raw_volume_does_not_hide_missing_pit_evidence() -> None:
    result = assess_historical_dataset_readiness(
        replace(
            _metrics(),
            tpex_archive_symbol_count=0,
            twse_verified_listing_period_count=0,
            tpex_verified_calendar_session_count=0,
            verified_company_action_coverage_count=0,
            unresolved_delisting_count=843,
            canonical_production_row_count=0,
        )
    )

    assert result.canonicalization_ready is False
    assert result.dataset_build_ready is False
    assert result.system_status == "RESEARCH_ONLY"
    assert "TPEX_ARCHIVE_SYMBOL_COVERAGE_INSUFFICIENT" in result.reason_codes
    assert "TWSE_LISTING_IDENTITY_COVERAGE_INSUFFICIENT" in result.reason_codes
    assert "TPEX_CALENDAR_COVERAGE_INSUFFICIENT" in result.reason_codes
    assert "COMPANY_ACTION_COVERAGE_EMPTY" in result.reason_codes
    assert "DELISTING_IDENTITIES_UNRESOLVED" in result.reason_codes
    assert "CANONICAL_PRODUCTION_ROWS_EMPTY" in result.reason_codes


def test_disjoint_aggregate_counts_cannot_unlock_dataset_build() -> None:
    result = assess_historical_dataset_readiness(
        replace(
            _metrics(),
            twse_pit_covered_archive_symbol_count=0,
            tpex_pit_covered_archive_symbol_count=0,
            pit_covered_trading_session_count=0,
        )
    )

    assert result.dataset_build_ready is False
    assert (
        "TWSE_POINT_IN_TIME_COVERAGE_INTERSECTION_INSUFFICIENT" in result.reason_codes
    )
    assert (
        "TPEX_POINT_IN_TIME_COVERAGE_INTERSECTION_INSUFFICIENT" in result.reason_codes
    )
    assert (
        "POINT_IN_TIME_SESSION_COVERAGE_INTERSECTION_INSUFFICIENT"
        in result.reason_codes
    )


def test_unavailable_metric_is_not_silently_treated_as_zero() -> None:
    result = assess_historical_dataset_readiness(
        replace(_metrics(), twse_verified_listing_period_count=None)
    )

    assert result.dataset_build_ready is False
    assert "TWSE_VERIFIED_LISTING_PERIOD_COUNT_UNAVAILABLE" in result.reason_codes
    assert "TWSE_LISTING_IDENTITY_COVERAGE_INSUFFICIENT" not in result.reason_codes


def test_archive_integrity_failure_marks_system_fail() -> None:
    result = assess_historical_dataset_readiness(
        replace(_metrics(), archive_integrity_status="FAIL")
    )

    assert result.system_status == "FAIL"
    assert result.reason_codes[0] == "ARCHIVE_INTEGRITY_FAILED"


def test_thresholds_are_explicit_and_configurable() -> None:
    result = assess_historical_dataset_readiness(
        replace(
            _metrics(),
            twse_archive_symbol_count=1,
            tpex_archive_symbol_count=1,
            twse_verified_listing_period_count=1,
            tpex_verified_listing_period_count=1,
            twse_verified_calendar_session_count=1,
            tpex_verified_calendar_session_count=1,
        ),
        thresholds=HistoricalDatasetReadinessThresholds(
            minimum_archive_rows=1,
            minimum_twse_symbols=1,
            minimum_tpex_symbols=1,
            minimum_calendar_sessions=1,
            minimum_security_states=1,
            minimum_company_action_coverage_rows=1,
            minimum_canonical_rows=1,
        ),
    )

    assert result.dataset_build_ready is True


def test_canonical_rows_are_a_dataset_output_not_a_prebuild_prerequisite() -> None:
    result = assess_historical_dataset_readiness(
        replace(_metrics(), canonical_production_row_count=0)
    )

    assert result.canonicalization_ready is True
    assert result.canonicalization_status == "READY_FOR_CANONICALIZATION"
    assert result.canonicalization_reason_codes == ()
    assert result.dataset_build_ready is False
    assert result.readiness_status == "READY_FOR_CANONICALIZATION"
    assert result.reason_codes == ("CANONICAL_PRODUCTION_ROWS_EMPTY",)


def test_missing_canonical_row_aggregate_does_not_block_canonicalization() -> None:
    result = assess_historical_dataset_readiness(
        replace(_metrics(), canonical_production_row_count=None)
    )

    assert result.canonicalization_ready is True
    assert result.dataset_build_ready is False
    assert result.reason_codes == ("CANONICAL_ROW_COUNT_UNAVAILABLE",)


def test_unavailable_canonical_contract_blocks_canonicalization() -> None:
    result = assess_historical_dataset_readiness(
        replace(_metrics(), canonical_contract_object_count=None)
    )

    assert result.canonicalization_ready is False
    assert result.canonicalization_status == "BLOCKED"
    assert result.dataset_build_ready is False
    assert "CANONICAL_CONTRACT_UNAVAILABLE" in result.canonicalization_reason_codes
    assert "CANONICAL_CONTRACT_UNAVAILABLE" in result.reason_codes


def test_empty_but_available_canonical_contract_allows_canonicalization() -> None:
    result = assess_historical_dataset_readiness(
        replace(
            _metrics(),
            canonical_contract_object_count=0,
            canonical_production_row_count=0,
        )
    )

    assert result.canonicalization_ready is True
    assert result.canonicalization_reason_codes == ()
    assert result.dataset_build_ready is False
    assert result.reason_codes == ("CANONICAL_PRODUCTION_ROWS_EMPTY",)
