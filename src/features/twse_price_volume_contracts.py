"""Backward-compatible TWSE contracts backed by venue-neutral types."""

from .price_volume_contracts import (
    FeatureValueAudit,
    PriceVolumeFeatureBuildResult,
    PriceVolumeFeatureRow,
    strict_point_in_time_audit_pass,
)
from .twse_price_volume_schema import (
    TWSE_PRICE_VOLUME_AVAILABILITY_MODES,
    TWSE_PRICE_VOLUME_FEATURE_FORMULAS,
    TWSE_PRICE_VOLUME_FEATURE_NAMES,
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
    TWSE_PRICE_VOLUME_PRICE_BASIS,
    TWSE_RESEARCH_SCHEDULING_HINT_REASON,
)

TwsePriceVolumeFeatureRow = PriceVolumeFeatureRow
TwsePriceVolumeFeatureBuildResult = PriceVolumeFeatureBuildResult

__all__ = [
    "FeatureValueAudit",
    "TWSE_PRICE_VOLUME_AVAILABILITY_MODES",
    "TWSE_PRICE_VOLUME_FEATURE_FORMULAS",
    "TWSE_PRICE_VOLUME_FEATURE_NAMES",
    "TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH",
    "TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION",
    "TWSE_PRICE_VOLUME_PRICE_BASIS",
    "TWSE_RESEARCH_SCHEDULING_HINT_REASON",
    "TwsePriceVolumeFeatureBuildResult",
    "TwsePriceVolumeFeatureRow",
    "strict_point_in_time_audit_pass",
]
