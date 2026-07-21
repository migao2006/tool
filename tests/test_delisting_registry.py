from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.delisting_registry import normalize_delisting_registry
from src.data.providers.contracts import ProviderPayload
from tests.support.delisting_registry_fixtures import tpex_payload, twse_payload


def test_twse_registry_preserves_event_without_linking_current_security() -> None:
    payload = twse_payload()

    result = normalize_delisting_registry(payload, market="TWSE", source_id=10)

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row["listing_market"] == "TWSE"
    assert row["source_symbol"] == "6806"
    assert row["source_name"] == "測試上市公司"
    assert row["termination_date"] == "2026-06-23"
    assert row["termination_reason_raw"] is None
    assert row["available_at"] == payload.retrieved_at.isoformat()
    assert row["first_observed_at"] == payload.retrieved_at.isoformat()
    assert row["available_at_basis"] == "FIRST_OBSERVED_AT_RETRIEVAL"
    assert row["identity_resolution_status"] == "UNRESOLVED"
    assert row["system_status"] == "RESEARCH_ONLY"
    assert "security_id" not in row


def test_tpex_registry_maps_named_fields_and_trims_symbol() -> None:
    result = normalize_delisting_registry(
        tpex_payload(
            [["1752 ", "測試公司", "81-10-27", "測試原因", "https://example.test"]]
        ),
        market="TPEX",
        source_id=20,
    )

    row = result.rows[0]
    assert row["source_symbol"] == "1752"
    assert row["termination_date"] == "1992-10-27"
    assert row["termination_reason_raw"] == "測試原因"
    source_row = row["source_row"]
    assert isinstance(source_row, dict)
    assert source_row["股票代號"] == "1752 "


def test_event_id_is_stable_while_source_revision_remains_auditable() -> None:
    first = normalize_delisting_registry(
        twse_payload(
            [{"DelistingDate": "115/06/23", "Company": "舊名稱", "Code": "6806"}]
        ),
        market="TWSE",
        source_id=10,
    ).rows[0]
    revised = normalize_delisting_registry(
        twse_payload(
            [{"DelistingDate": "115/06/23", "Company": "新名稱", "Code": "6806"}]
        ),
        market="TWSE",
        source_id=10,
    ).rows[0]

    assert first["source_event_id"] == revised["source_event_id"]
    assert first["source_revision_hash"] != revised["source_revision_hash"]


def test_same_symbol_with_different_termination_dates_is_not_merged() -> None:
    result = normalize_delisting_registry(
        twse_payload(
            [
                {"DelistingDate": "100/01/01", "Company": "甲", "Code": "1234"},
                {"DelistingDate": "115/01/01", "Company": "乙", "Code": "1234"},
            ]
        ),
        market="TWSE",
        source_id=10,
    )

    assert len(result.rows) == 2
    assert len({row["source_event_id"] for row in result.rows}) == 2


def test_conflicting_rows_for_same_event_fail_closed() -> None:
    with pytest.raises(IngestionError) as captured:
        _ = normalize_delisting_registry(
            twse_payload(
                [
                    {"DelistingDate": "115/01/01", "Company": "甲", "Code": "1234"},
                    {"DelistingDate": "115/01/01", "Company": "乙", "Code": "1234"},
                ]
            ),
            market="TWSE",
            source_id=10,
        )

    assert captured.value.reason_code == "DELISTING_DUPLICATE_CONFLICT"


@pytest.mark.parametrize(
    "payload",
    [
        tpex_payload(total_count=2),
        tpex_payload(fields=["unexpected"]),
        tpex_payload(stat="參數輸入錯誤"),
    ],
)
def test_tpex_registry_rejects_truncated_or_changed_payload(
    payload: ProviderPayload,
) -> None:
    with pytest.raises(IngestionError):
        _ = normalize_delisting_registry(payload, market="TPEX", source_id=20)


def test_termination_date_never_replaces_first_observed_time() -> None:
    retrieved_at = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)
    row = normalize_delisting_registry(
        twse_payload(retrieved_at=retrieved_at),
        market="TWSE",
        source_id=10,
    ).rows[0]

    assert row["termination_date"] == "2026-06-23"
    assert row["available_at"] == "2026-07-18T06:00:00+00:00"


def test_missing_symbol_or_date_is_not_silently_excluded() -> None:
    with pytest.raises(IngestionError) as captured:
        _ = normalize_delisting_registry(
            twse_payload([{"DelistingDate": "", "Company": "甲", "Code": ""}]),
            market="TWSE",
            source_id=10,
        )

    assert captured.value.reason_code == "DELISTING_ROW_INCOMPLETE"
