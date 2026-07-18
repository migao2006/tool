from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from src.data.ingestion.historical_archive_contracts import HistoricalArchiveRequest
from src.data.ingestion.historical_object_key import build_historical_object_key


def _request(
    *, market: str = "TWSE", retrieved_at: datetime
) -> HistoricalArchiveRequest:
    return HistoricalArchiveRequest(
        scheduled_market=market,
        asset_type="COMMON_STOCK",
        source_symbol="2330",
        requested_start_date=date(2020, 1, 1),
        requested_end_date=date(2026, 7, 18),
        source_payload_sha256="b" * 64,
        retrieved_at=retrieved_at,
    )


def test_object_key_is_deterministic_and_utc_normalized() -> None:
    taipei = _request(
        retrieved_at=datetime(
            2026,
            7,
            18,
            14,
            30,
            12,
            123456,
            tzinfo=timezone(timedelta(hours=8)),
        )
    )
    utc = _request(
        retrieved_at=datetime(
            2026,
            7,
            18,
            6,
            30,
            12,
            123456,
            tzinfo=timezone.utc,
        )
    )

    expected = (
        "raw/v1/provider=finmind/dataset=daily_bars/scheduled_market=TWSE/"
        "asset_type=COMMON_STOCK/symbol=2330/"
        "request_start=2020-01-01/request_end=2026-07-18/"
        f"payload_sha256={'b' * 64}.parquet"
    )
    assert build_historical_object_key(taipei) == expected
    assert build_historical_object_key(utc) == expected


def test_object_key_uses_scheduled_market_not_resolved_market_semantics() -> None:
    observed_at = datetime(2026, 7, 18, 6, tzinfo=timezone.utc)
    twse_key = build_historical_object_key(
        _request(market="TWSE", retrieved_at=observed_at)
    )
    tpex_key = build_historical_object_key(
        _request(market="TPEX", retrieved_at=observed_at)
    )

    assert "scheduled_market=TWSE" in twse_key
    assert "scheduled_market=TPEX" in tpex_key
    assert "/market=" not in twse_key
    assert twse_key != tpex_key
    assert not twse_key.startswith("/")
    assert "\\" not in twse_key
    assert ".." not in twse_key.split("/")
