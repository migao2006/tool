"""Venue profiles for common-stock archive feature artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from src.features.price_volume_schema import (
    PriceVolumeFeatureSpec,
    price_volume_feature_spec,
)


@dataclass(frozen=True)
class ArchiveFeatureMarketProfile:
    market: str
    provider_code: str
    scope_filters: Mapping[str, str]
    dataset_version: str
    decision_time_policy_version: str
    feature: PriceVolumeFeatureSpec
    global_reason_codes: tuple[str, ...]


_COMMON_REASONS = (
    "CURRENT_SECURITIES_SURVIVORSHIP_MAPPING",
    "HISTORICAL_IDENTITY_NOT_POINT_IN_TIME",
    "TRADING_SESSIONS_DERIVED_PER_SYMBOL",
    "RESEARCH_SCHEDULING_HINT",
    "LABELS_NOT_ASSEMBLED",
    "BENCHMARK_ARCHIVE_NOT_CONNECTED",
)


ARCHIVE_FEATURE_MARKET_PROFILES = {
    market: ArchiveFeatureMarketProfile(
        market=market,
        provider_code="FINMIND",
        scope_filters=MappingProxyType(
            {
                "source_dataset": "eq.daily_bars",
                "scheduled_market": f"eq.{market}",
                "asset_type": "eq.COMMON_STOCK",
            }
        ),
        dataset_version=f"{market.lower()}-archive-price-volume-5d-v2",
        decision_time_policy_version=(
            f"{market.lower()}-post-close-1700-asia-taipei-v1"
        ),
        feature=price_volume_feature_spec(market),
        global_reason_codes=_COMMON_REASONS,
    )
    for market in ("TWSE", "TPEX")
}


def archive_feature_market_profile(market: str) -> ArchiveFeatureMarketProfile:
    try:
        return ARCHIVE_FEATURE_MARKET_PROFILES[market]
    except KeyError as error:
        raise ValueError("archive features support only TWSE or TPEX") from error


__all__ = ["ArchiveFeatureMarketProfile", "archive_feature_market_profile"]
