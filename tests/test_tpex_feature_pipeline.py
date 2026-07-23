from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from hashlib import sha256
from typing import final
from zoneinfo import ZoneInfo

import pytest

from src.data.ingestion.historical_archive_contracts import (
    HISTORICAL_ARCHIVE_SCHEMA_VERSION,
)
from src.data.research.archive_feature_contracts import ArchiveFeatureBuildError
from src.data.research.archive_feature_rows import group_manifests
from src.data.research.tpex_archive_feature_contracts import (
    TPEX_ARCHIVE_FEATURE_DATASET_VERSION,
    TPEX_ARCHIVE_SCOPE_FILTERS,
)
from src.data.research.tpex_current_identity_repository import (
    TpexCurrentIdentityRepository,
)
from src.features.tpex_price_volume_builder import build_tpex_price_volume_features
from src.features.tpex_price_volume_schema import (
    TPEX_PRICE_VOLUME_FEATURE_NAMES,
    TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
    TPEX_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
)
from src.features.twse_price_volume_schema import (
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
)


TAIPEI = ZoneInfo("Asia/Taipei")


def _tpex_bars(count: int = 70) -> list[dict[str, object]]:
    start = date(2025, 1, 2)
    rows: list[dict[str, object]] = []
    for index in range(count):
        trade_date = start + timedelta(days=index)
        close = 50.0 + index
        volume = 500_000.0 + index
        rows.append(
            {
                "security_id": 5483,
                "listing_period_id": "TPEX:5483:2003-01-02",
                "market": "TPEX",
                "symbol": "5483",
                "asset_type": "COMMON_STOCK",
                "trade_date": trade_date,
                "decision_at": datetime.combine(
                    trade_date,
                    datetime.min.time().replace(hour=17),
                    tzinfo=TAIPEI,
                ),
                "available_at": datetime.combine(
                    trade_date,
                    datetime.min.time().replace(hour=16),
                    tzinfo=TAIPEI,
                ),
                "available_at_basis": "OFFICIAL_PUBLICATION_AT",
                "open_price": close - 0.5,
                "high_price": close + 1.0,
                "low_price": close - 1.0,
                "close_price": close,
                "trading_volume": volume,
                "trading_value": close * volume,
                "point_in_time_status": "VERIFIED",
                "parse_status": "PARSED",
                "reason_codes": (),
            }
        )
    return rows


def _manifest(
    *, market: str = "TPEX", asset_type: str = "COMMON_STOCK"
) -> dict[str, object]:
    bucket = "alpha-lens-archive"
    object_key = f"historical/finmind/daily_bars/{market.lower()}/5483.parquet"
    return {
        "archive_id": 1,
        "archive_key": sha256(f"{bucket}\0{object_key}".encode()).hexdigest(),
        "storage_provider": "CLOUDFLARE_R2",
        "bucket_name": bucket,
        "object_key": object_key,
        "object_etag": '"etag"',
        "schema_version": HISTORICAL_ARCHIVE_SCHEMA_VERSION,
        "provider_code": "FINMIND",
        "source_dataset": "daily_bars",
        "source_version": "api.v4",
        "source_symbol": "5483",
        "scheduled_market": market,
        "asset_type": asset_type,
        "requested_start_date": "2025-01-02",
        "requested_end_date": "2025-03-31",
        "min_trade_date": "2025-01-02",
        "max_trade_date": "2025-03-31",
        "source_payload_hash": "a" * 64,
        "parquet_sha256": "b" * 64,
        "byte_size": 1,
        "row_count": 1,
        "parsed_row_count": 1,
        "quarantined_row_count": 0,
        "first_observed_at": "2026-07-20T00:00:00+00:00",
        "point_in_time_status": "UNVERIFIED",
        "usage_scope": "RAW_LANDING_ONLY",
        "system_status": "RESEARCH_ONLY",
        "reason_codes": ["POINT_IN_TIME_UNVERIFIED", "RAW_LANDING_ONLY"],
    }


@final
class FakeSecuritySource:
    def __init__(self) -> None:
        self.calls: list[Mapping[str, str]] = []

    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]:
        assert table == "securities"
        assert "asset_type" in select
        normalized = dict(filters or {})
        self.calls.append(normalized)
        if normalized["security_id"] != "gt.0":
            return []
        rows: list[dict[str, object]] = [
            {
                "security_id": 5483,
                "symbol": "5483",
                "market": "TPEX",
                "asset_type": "COMMON_STOCK",
                "listing_date": "2003-01-02",
                "delisting_date": None,
            }
        ]
        return rows[:limit]


def test_tpex_build_has_17_separate_research_only_features() -> None:
    result = build_tpex_price_volume_features(_tpex_bars())
    row = result.rows[-1]

    assert len(TPEX_PRICE_VOLUME_FEATURE_NAMES) == 17
    assert tuple(row.feature_values) == TPEX_PRICE_VOLUME_FEATURE_NAMES
    assert result.market == row.market == "TPEX"
    assert result.feature_schema_version == TPEX_PRICE_VOLUME_FEATURE_SCHEMA_VERSION
    assert result.feature_schema_hash == TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH
    assert (
        TPEX_PRICE_VOLUME_FEATURE_SCHEMA_VERSION
        != TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION
    )
    assert (
        TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH != TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH
    )
    assert row.hard_fail is False
    assert row.usage_scope == "FEATURE_RESEARCH_ONLY"
    assert result.system_status == row.system_status == "RESEARCH_ONLY"
    assert TPEX_ARCHIVE_FEATURE_DATASET_VERSION.startswith("tpex-")


def test_tpex_current_identity_query_is_common_stock_only() -> None:
    source = FakeSecuritySource()

    snapshot = TpexCurrentIdentityRepository(source).fetch()

    assert tuple(snapshot.by_symbol) == ("5483",)
    assert snapshot.by_symbol["5483"].market == "TPEX"
    assert all(call["market"] == "eq.TPEX" for call in source.calls)
    assert all(call["asset_type"] == "eq.COMMON_STOCK" for call in source.calls)
    assert TPEX_ARCHIVE_SCOPE_FILTERS["scheduled_market"] == "eq.TPEX"
    assert TPEX_ARCHIVE_SCOPE_FILTERS["asset_type"] == "eq.COMMON_STOCK"


def test_tpex_manifest_scope_accepts_only_tpex_common_stock() -> None:
    accepted = group_manifests((_manifest(),), market="TPEX")
    assert tuple(accepted) == ("5483",)

    earlier = _manifest()
    earlier.update(
        {
            "archive_id": 2,
            "requested_end_date": "2025-01-31",
            "max_trade_date": "2025-01-31",
        }
    )
    later = _manifest()
    later.update(
        {
            "archive_id": 1,
            "requested_start_date": "2025-02-01",
            "min_trade_date": "2025-02-01",
        }
    )
    ordered = group_manifests((later, earlier), market="TPEX")
    assert [row["archive_id"] for row in ordered["5483"]] == [2, 1]

    for rejected in (
        _manifest(market="TWSE"),
        _manifest(asset_type="ETF"),
    ):
        with pytest.raises(ArchiveFeatureBuildError) as captured:
            group_manifests((rejected,), market="TPEX")
        assert captured.value.reason_code == "TPEX_ARCHIVE_SCOPE_MISMATCH"
