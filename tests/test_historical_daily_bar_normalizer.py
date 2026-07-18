from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.historical_daily_bar_normalizer import (
    normalize_historical_daily_bars,
)
from src.data.providers.contracts import ProviderPayload


RETRIEVED_AT = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)


def payload(rows: list[object]) -> ProviderPayload:
    body = {"status": 200, "data": rows}
    digest = sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return ProviderPayload(
        provider="FINMIND",
        dataset="daily_bars",
        source_version="api.v4",
        source_url="https://api.finmindtrade.com/api/v4/data",
        retrieved_at=RETRIEVED_AT,
        payload_sha256=digest,
        payload=body,
    )


def valid_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "date": "2020-01-02",
        "stock_id": "2330",
        "Trading_Volume": 34_000_000,
        "Trading_money": 11_500_000_000,
        "open": 332.5,
        "max": 339.0,
        "min": 332.5,
        "close": 339.0,
        "spread": 8.0,
        "Trading_turnover": 30_115,
    }
    row.update(updates)
    return row


def test_parsed_row_is_unresolved_research_only_raw_landing() -> None:
    source = payload([valid_row()])

    result = normalize_historical_daily_bars(source)

    assert result.source_row_count == result.parsed_count == 1
    assert result.quarantined_count == 0
    row = result.landing_rows[0]
    assert row["source_symbol"] == "2330"
    assert row["trade_date"] == "2020-01-02"
    assert row["open_price"] == "332.5"
    assert row["high_price"] == "339.0"
    assert row["low_price"] == "332.5"
    assert row["close_price"] == "339.0"
    assert row["trading_volume"] == "34000000"
    assert row["trading_value"] == "11500000000"
    assert row["trade_count"] == 30115
    assert row["source_market_claim"] is None
    assert row["source_market_basis"] == "UNAVAILABLE"
    assert row["available_at"] == source.retrieved_at.isoformat()
    assert row["first_observed_at"] == source.retrieved_at.isoformat()
    assert row["available_at_basis"] == "FIRST_OBSERVED_AT_RETRIEVAL"
    assert row["identity_resolution_status"] == "UNRESOLVED"
    assert row["point_in_time_status"] == "UNVERIFIED"
    assert row["usage_scope"] == "RAW_LANDING_ONLY"
    assert row["system_status"] == "RESEARCH_ONLY"
    assert row["parse_status"] == "PARSED"
    assert len(str(row["landing_key"])) == 64
    assert len(str(row["source_revision_hash"])) == 64
    assert "security_id" not in row


def test_retrieval_time_never_backdates_availability_to_trade_date() -> None:
    row = normalize_historical_daily_bars(payload([valid_row()])).landing_rows[0]

    assert row["trade_date"] == "2020-01-02"
    assert row["available_at"] == "2026-07-18T06:00:00+00:00"


@pytest.mark.parametrize(
    ("updates", "reason_code"),
    [
        ({"open": "not-a-number"}, "OPEN_PRICE_INVALID"),
        ({"Trading_Volume": -1}, "TRADING_VOLUME_NEGATIVE"),
        ({"max": 330}, "OHLC_RANGE_INVALID"),
        ({"min": 340}, "OHLC_RANGE_INVALID"),
        ({"close": 0}, "OHLC_NON_POSITIVE"),
        ({"date": "2020-02-31"}, "TRADE_DATE_INVALID"),
    ],
)
def test_invalid_rows_are_quarantined(
    updates: dict[str, object], reason_code: str
) -> None:
    result = normalize_historical_daily_bars(payload([valid_row(**updates)]))

    assert result.source_row_count == result.quarantined_count == 1
    assert result.parsed_count == 0
    row = result.landing_rows[0]
    assert row["parse_status"] == "QUARANTINED"
    assert reason_code in row["reason_codes"]
    assert row["usage_scope"] == "RAW_LANDING_ONLY"
    assert "security_id" not in row
    assert any(
        issue["reason_code"] == reason_code
        and issue["landing_key"] == row["landing_key"]
        for issue in result.quarantine_rows
    )


def test_every_data_element_is_accounted_for_without_silent_drop() -> None:
    result = normalize_historical_daily_bars(
        payload([valid_row(), {"date": "bad"}, "not-an-object"])
    )

    assert result.source_row_count == 3
    assert len(result.landing_rows) == 3
    assert result.parsed_count == 1
    assert result.quarantined_count == 2
    assert "SOURCE_SYMBOL_MISSING" in result.landing_rows[1]["reason_codes"]
    assert "ROW_NOT_OBJECT" in result.landing_rows[2]["reason_codes"]
    assert result.landing_rows[2]["source_row"] == "not-an-object"


def test_landing_key_and_revision_hash_track_row_revisions() -> None:
    first = normalize_historical_daily_bars(
        payload([valid_row(close=339.0)])
    ).landing_rows[0]
    revised = normalize_historical_daily_bars(
        payload([valid_row(close=338.0)])
    ).landing_rows[0]

    assert first["landing_key"] != revised["landing_key"]
    assert first["source_revision_hash"] != revised["source_revision_hash"]


def test_canonical_revision_hash_does_not_depend_on_mapping_order() -> None:
    row = valid_row()
    reversed_row = dict(reversed(list(row.items())))

    first = normalize_historical_daily_bars(payload([row])).landing_rows[0]
    second = normalize_historical_daily_bars(payload([reversed_row])).landing_rows[0]

    assert first["landing_key"] == second["landing_key"]
    assert first["source_revision_hash"] == second["source_revision_hash"]


@pytest.mark.parametrize(
    "source",
    [
        ProviderPayload(
            provider="FINMIND",
            dataset="daily_bars",
            source_version="api.v4",
            source_url="https://example.test/data",
            retrieved_at=RETRIEVED_AT,
            payload_sha256="0" * 64,
            payload=[],
        ),
        ProviderPayload(
            provider="FINMIND",
            dataset="daily_bars",
            source_version="api.v4",
            source_url="https://example.test/data",
            retrieved_at=RETRIEVED_AT,
            payload_sha256="0" * 64,
            payload={"data": "not-a-list"},
        ),
    ],
)
def test_payload_must_follow_finmind_data_array_contract(
    source: ProviderPayload,
) -> None:
    with pytest.raises(IngestionError) as captured:
        normalize_historical_daily_bars(source)

    assert captured.value.reason_code == "HISTORICAL_DAILY_BAR_PAYLOAD_INVALID"


def test_source_contract_must_be_finmind_daily_bars() -> None:
    source = payload([valid_row()])
    wrong = ProviderPayload(
        provider="FINMIND",
        dataset="adjusted_bars",
        source_version=source.source_version,
        source_url=source.source_url,
        retrieved_at=source.retrieved_at,
        payload_sha256=source.payload_sha256,
        payload=source.payload,
    )

    with pytest.raises(IngestionError) as captured:
        normalize_historical_daily_bars(wrong)

    assert captured.value.reason_code == "HISTORICAL_DAILY_BAR_SOURCE_INVALID"
