"""TPEX common-stock entry point for the shared 17 price/volume features."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from .price_volume_availability import AvailabilityMode
from .price_volume_builder import build_price_volume_features
from .price_volume_contracts import PriceVolumeFeatureBuildResult


def build_tpex_price_volume_features(
    records: object,
    *,
    trading_sessions: Sequence[date] | None = None,
    availability_mode: AvailabilityMode = "STRICT_CANONICAL",
) -> PriceVolumeFeatureBuildResult:
    """Build research-only TPEX common-stock features without storage access."""

    return build_price_volume_features(
        records,
        market="TPEX",
        trading_sessions=trading_sessions,
        availability_mode=availability_mode,
    )


__all__ = ["build_tpex_price_volume_features"]
