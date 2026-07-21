from __future__ import annotations

from datetime import date
from typing import cast

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.twse_current_listing_identity import (
    normalize_twse_current_listing_identities,
)
from tests.support.twse_current_listing_identity_fixtures import (
    mops_payload,
    profile_row,
)


def test_current_profile_stays_unresolved_and_unlinked() -> None:
    payload = mops_payload()
    normalized = normalize_twse_current_listing_identities(payload, source_id=7)

    assert len(normalized.rows) == 1
    row = normalized.rows[0]
    assert row["listing_period_id"] == "RESEARCH:MOPS:TWSE:2330:1994-09-05"
    assert row["security_id"] is None
    assert row["isin"] is None
    assert row["identity_resolution_status"] == "UNRESOLVED"
    assert row["available_at_basis"] == "FIRST_OBSERVED_AT_RETRIEVAL"
    assert row["usage_scope"] == "IDENTITY_RESEARCH_ONLY"
    assert row["system_status"] == "RESEARCH_ONLY"
    reason_codes = cast(list[str], row["reason_codes"])
    assert "ISIN_UNAVAILABLE" in reason_codes
    assert "SECURITY_ID_NOT_LINKED" in reason_codes
    assert row["source_payload_hash"] == payload.payload_sha256
    assert row["source_row"] == profile_row()
    assert normalized.registration_id_rows == 1
    assert normalized.listing_date_min == date(1994, 9, 5)


def test_non_common_securities_are_excluded_without_becoming_identities() -> None:
    normalized = normalize_twse_current_listing_identities(
        mops_payload(
            [
                profile_row(),
                profile_row("006208", name="ETF"),
                profile_row("9103", name="存託憑證"),
            ]
        ),
        source_id=7,
    )

    assert [row["source_symbol"] for row in normalized.rows] == ["2330"]
    assert normalized.excluded_non_common_stock_rows == 2


def test_missing_registration_id_is_visible_but_not_fabricated() -> None:
    normalized = normalize_twse_current_listing_identities(
        mops_payload([profile_row(registration_id=None)]),
        source_id=7,
    )

    row = normalized.rows[0]
    assert normalized.registration_id_rows == 0
    reason_codes = cast(list[str], row["reason_codes"])
    source_row = cast(dict[str, object], row["source_row"])
    assert "COMPANY_REGISTRATION_ID_UNAVAILABLE" in reason_codes
    assert "營利事業統一編號" not in source_row


@pytest.mark.parametrize(
    ("provider", "dataset"),
    [("TWSE", "listed_company_profile"), ("MOPS", "otc_company_profile")],
)
def test_wrong_source_contract_is_rejected(provider: str, dataset: str) -> None:
    with pytest.raises(IngestionError) as captured:
        _ = normalize_twse_current_listing_identities(
            mops_payload(provider=provider, dataset=dataset),
            source_id=7,
        )
    assert captured.value.reason_code == "CURRENT_LISTING_IDENTITY_SOURCE_INVALID"


@pytest.mark.parametrize(
    "row",
    [
        {**profile_row(name=""), "公司簡稱": ""},
        profile_row(listing_date=None),
    ],
)
def test_common_stock_missing_critical_identity_fails_closed(
    row: dict[str, object],
) -> None:
    with pytest.raises(IngestionError) as captured:
        _ = normalize_twse_current_listing_identities(
            mops_payload([row]), source_id=7
        )
    assert captured.value.reason_code == "CURRENT_LISTING_IDENTITY_ROW_INCOMPLETE"


def test_conflicting_duplicate_listing_rows_fail_closed() -> None:
    with pytest.raises(IngestionError) as captured:
        _ = normalize_twse_current_listing_identities(
            mops_payload([profile_row(), profile_row(name="不同公司")]),
            source_id=7,
        )
    assert captured.value.reason_code == (
        "CURRENT_LISTING_IDENTITY_DUPLICATE_CONFLICT"
    )


def test_row_revision_changes_without_changing_research_listing_key() -> None:
    first = normalize_twse_current_listing_identities(mops_payload(), source_id=7)
    revised = normalize_twse_current_listing_identities(
        mops_payload([profile_row(name="更名後公司")]),
        source_id=7,
    )

    assert first.rows[0]["listing_period_id"] == revised.rows[0]["listing_period_id"]
    assert first.rows[0]["source_event_id"] == revised.rows[0]["source_event_id"]
    assert first.rows[0]["source_revision_hash"] != revised.rows[0][
        "source_revision_hash"
    ]
