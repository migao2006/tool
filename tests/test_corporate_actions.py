from __future__ import annotations

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.corporate_actions import normalize_announced_corporate_actions
from tests.support.corporate_action_fixtures import (
    provider_payload,
    security_ids,
    tpex_forecast_payload,
    twse_payload,
)


@pytest.mark.parametrize(
    ("payload", "market"),
    [
        (provider_payload("TPEX", "ex_rights_forecast", []), "TWSE"),
        (provider_payload("TWSE", "ex_rights", []), "TPEX"),
        (provider_payload("TWSE", "daily_bars", []), "TWSE"),
    ],
)
def test_normalizer_requires_the_official_market_provider_contract(
    payload: object, market: str
) -> None:
    with pytest.raises(IngestionError) as captured:
        normalize_announced_corporate_actions(
            payload, market=market, source_id=1, security_ids=security_ids()
        )

    assert captured.value.reason_code == "CORPORATE_ACTION_SOURCE_INVALID"


def test_normalizer_maps_cash_and_stock_and_marks_omitted_rights_incomplete() -> None:
    twse = normalize_announced_corporate_actions(
        twse_payload(), market="TWSE", source_id=11, security_ids=security_ids()
    )
    tpex = normalize_announced_corporate_actions(
        tpex_forecast_payload(), market="TPEX", source_id=22, security_ids=security_ids()
    )

    assert [(row["action_type"], row["security_id"]) for row in twse.rows] == [
        ("CASH_DIVIDEND", 101),
        ("STOCK_DIVIDEND", 101),
    ]
    assert twse.rows[0]["cash_amount_per_share"] == "2.5"
    assert twse.rows[1]["share_ratio"] == "0.1"
    assert twse.rows[1]["share_multiplier"] == "1.1"
    assert {row["source_row_complete"] for row in twse.rows} == {False}
    assert {row["announced_at"] for row in twse.rows} == {None}
    assert {row["first_observed_at"] for row in twse.rows} == {
        "2026-07-18T06:00:00+00:00"
    }
    assert {row["available_at_basis"] for row in twse.rows} == {
        "FIRST_OBSERVED_AT_RETRIEVAL"
    }
    assert all(len(str(row["source_revision_hash"])) == 64 for row in twse.rows)
    assert all(len(str(row["source_payload_hash"])) == 64 for row in twse.rows)
    assert twse.rows[0]["source_event_id"] == (
        "ex_rights:2330:CASH_DIVIDEND:2026-07-20"
    )
    assert len(tpex.rows) == 1
    assert tpex.rows[0]["action_type"] == "STOCK_DIVIDEND"
    assert tpex.rows[0]["share_ratio"] == "0.05"
    assert tpex.rows[0]["source_row_complete"] is False
    assert tpex.omitted_rights_components == 1
    assert tpex.unresolved_announced_components == 1


def test_normalizer_distinguishes_a_zero_dividend_from_a_missing_forecast_amount() -> None:
    payload = tpex_forecast_payload(
        [
            {
                "SecuritiesCompanyCode": "6488",
                "ExRrightsExDividendDate": "20260721",
                "CashDividend": "",
                "StockDividendRatio": "0.05",
                "SubscriptionRatioToNewSharesIssued": "0",
                "ExRrightsExDividend": "\u9664\u606f",
            }
        ]
    )

    normalized = normalize_announced_corporate_actions(
        payload, market="TPEX", source_id=22, security_ids=security_ids()
    )

    assert normalized.rows[0]["source_row_complete"] is False
    assert normalized.unresolved_announced_components == 1


def test_normalizer_excludes_unknown_and_explicit_zero_actions() -> None:
    payload = twse_payload(
        [
            {
                "Code": "9999",
                "Date": "1150720",
                "CashDividend": "3",
                "StockDividendRatio": "0",
                "SubscriptionRatio": "0",
            },
            {
                "Code": "2330",
                "Date": "1150720",
                "CashDividend": "0",
                "StockDividendRatio": "0",
                "SubscriptionRatio": "0",
            },
        ]
    )

    normalized = normalize_announced_corporate_actions(
        payload, market="TWSE", source_id=11, security_ids=security_ids()
    )

    assert normalized.rows == ()
    assert normalized.excluded_unknown_securities == 1
    assert normalized.excluded_no_supported_component_rows == 1


@pytest.mark.parametrize(
    ("cash", "stock"), [("-0.01", "0"), ("not-a-number", "0"), ("0", "NaN")]
)
def test_normalizer_rejects_negative_or_invalid_values(cash: str, stock: str) -> None:
    payload = twse_payload(
        [
            {
                "Code": "2330",
                "Date": "1150720",
                "CashDividend": cash,
                "StockDividendRatio": stock,
                "SubscriptionRatio": "0",
            }
        ]
    )

    with pytest.raises(IngestionError) as captured:
        normalize_announced_corporate_actions(
            payload, market="TWSE", source_id=11, security_ids=security_ids()
        )

    assert captured.value.reason_code == "CORPORATE_ACTION_VALUE_INVALID"


def test_normalizer_rejects_conflicting_duplicate_components() -> None:
    payload = twse_payload(
        [
            {
                "Code": "2330",
                "Date": "1150720",
                "CashDividend": "0",
                "StockDividendRatio": "0.1",
                "SubscriptionRatio": "0",
            },
            {
                "Code": "2330",
                "Date": "1150720",
                "CashDividend": "0",
                "StockDividendRatio": "0.2",
                "SubscriptionRatio": "0",
            },
        ]
    )

    with pytest.raises(IngestionError) as captured:
        normalize_announced_corporate_actions(
            payload, market="TWSE", source_id=11, security_ids=security_ids()
        )

    assert captured.value.reason_code == "CORPORATE_ACTION_DUPLICATE_CONFLICT"
