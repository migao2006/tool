from __future__ import annotations

from datetime import date

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.finmind_historical_evidence import (
    normalize_finmind_historical_evidence,
    validate_twse_common_symbols,
)
from tests.support.finmind_historical_evidence_fixtures import (
    RETRIEVED_AT,
    evidence_payloads,
    identity,
    payload,
)


START = date(2000, 1, 1)
END = date(2026, 7, 19)


def test_normalizer_keeps_action_lineage_and_canonical_suspension_event() -> None:
    normalized = normalize_finmind_historical_evidence(
        evidence_payloads(),
        source_id=7,
        symbols=("2330",),
        start_date=START,
        end_date=END,
        identities=(identity(),),
    )

    assert normalized.input_rows == 5
    assert normalized.excluded_outside_request == 1
    assert len(normalized.action_rows) == 3
    assert len(normalized.state_event_rows) == 1
    assert {row["action_type"] for row in normalized.action_rows} == {
        "CASH_DIVIDEND",
        "SPLIT",
    }
    assert all(row["source_id"] == 7 for row in normalized.action_rows)
    assert all(
        row["identity_resolution_status"] == "VERIFIED"
        for row in normalized.action_rows
    )
    assert all(
        row["usage_scope"] == "ACTION_RESEARCH_ONLY"
        and row["system_status"] == "RESEARCH_ONLY"
        and row["source_row_complete"] is False
        for row in normalized.action_rows
    )

    dividend = next(
        row
        for row in normalized.action_rows
        if row["source_dataset"] == "dividend_results"
    )
    split = next(
        row for row in normalized.action_rows if row["source_dataset"] == "stock_splits"
    )
    par_value = next(
        row
        for row in normalized.action_rows
        if row["source_dataset"] == "par_value_changes"
    )
    assert dividend["cash_amount_per_share"] is None
    assert dividend["reference_price_adjustment"] == "3"
    assert split["share_multiplier"] == "2"
    assert par_value["share_multiplier"] == "5"
    assert dividend["first_observed_at"] == RETRIEVED_AT.isoformat()
    assert dividend["available_at"] == RETRIEVED_AT.isoformat()
    assert dividend["available_at_basis"] == "FIRST_OBSERVED_AT_RETRIEVAL"
    assert len(str(dividend["source_revision_hash"])) == 64
    assert dividend["source_row"]["stock_id"] == "2330"  # type: ignore[index]

    state = normalized.state_event_rows[0]
    assert state["event_type"] == "TRADING_SUSPENSION_INTERVAL"
    assert state["suspension_at"] == "2023-01-10T07:00:00+00:00"
    assert state["resumption_at"] == "2023-01-12T01:00:00+00:00"
    assert state["identity_resolution_status"] == "VERIFIED"
    assert state["state_verification_status"] == "UNRESOLVED"
    assert state["usage_scope"] == "SECURITY_STATE_RESEARCH_ONLY"
    assert "COMPLETE_SECURITY_STATE_SNAPSHOT_UNAVAILABLE" in state["reason_codes"]


def test_combined_dividend_stays_other_unresolved_and_duplicates_are_ignored() -> None:
    combined = {
        "date": "2024-06-13",
        "stock_id": "2330",
        "before_price": 923,
        "after_price": 917,
        "stock_and_cache_dividend": 6,
        "stock_or_cache_dividend": "權息",
        "max_price": 1008,
        "min_price": 825,
        "open_price": 917,
        "reference_price": 917,
    }
    fixtures = evidence_payloads()
    normalized = normalize_finmind_historical_evidence(
        (payload("dividend_results", [combined, combined]), *fixtures[1:]),
        source_id=9,
        symbols=("2330",),
        start_date=START,
        end_date=END,
    )

    dividend = next(
        row
        for row in normalized.action_rows
        if row["source_dataset"] == "dividend_results"
    )
    assert dividend["action_type"] == "OTHER"
    assert dividend["identity_resolution_status"] == "UNRESOLVED"
    assert "HISTORICAL_IDENTITY_UNRESOLVED" in dividend["reason_codes"]
    assert (
        "COMBINED_OR_UNKNOWN_DIVIDEND_RESULT_NOT_DECOMPOSED" in dividend["reason_codes"]
    )
    assert normalized.excluded_duplicates == 1
    assert normalized.excluded_outside_request == 1


def test_source_url_with_token_is_rejected_without_echoing_it() -> None:
    fixtures = evidence_payloads()
    unsafe = payload(
        "dividend_results",
        [],
        source_url="https://api.finmindtrade.com/api/v4/data?token=secret-value",
    )

    with pytest.raises(IngestionError) as captured:
        normalize_finmind_historical_evidence(
            (unsafe, *fixtures[1:]),
            source_id=1,
            symbols=("2330",),
            start_date=START,
            end_date=END,
        )

    assert captured.value.reason_code == "FINMIND_SOURCE_URL_CONTAINS_CREDENTIAL"
    assert "secret-value" not in str(captured.value)


@pytest.mark.parametrize("symbol", ["0050", "9103", "2330A", ""])
def test_only_twse_common_stock_codes_are_accepted(symbol: str) -> None:
    with pytest.raises(IngestionError) as captured:
        validate_twse_common_symbols((symbol,))

    assert captured.value.reason_code == "FINMIND_HISTORICAL_SYMBOL_UNSUPPORTED"
