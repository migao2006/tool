"""TPEX latest feature reader with an exact market boundary."""

from __future__ import annotations

from typing import final

from src.data.research.tpex_feature_artifact_contracts import manifest_from_object
from src.data.research.tpex_feature_artifact_reader import TpexFeatureArtifactReader
from src.data.research.tpex_daily_feature_delta_verification import (
    daily_delta_manifest_from_object,
)
from src.data.research.tpex_daily_feature_delta_reader import (
    TpexDailyFeatureDeltaReader,
)
from src.features.tpex_price_volume_schema import TPEX_PRICE_VOLUME_FEATURE_NAMES

from .venue_latest_feature_repository import (
    LatestFeatureCrossSection,
    LatestFeatureRepository,
    LatestFeatureSourceError,
)


LatestTpexFeatureCrossSection = LatestFeatureCrossSection
LatestTpexFeatureSourceError = LatestFeatureSourceError


@final
class LatestTpexFeatureRepository(LatestFeatureRepository):
    def __init__(self) -> None:
        super().__init__(
            market="TPEX",
            feature_names=TPEX_PRICE_VOLUME_FEATURE_NAMES,
            manifest_parser=manifest_from_object,
            reader=TpexFeatureArtifactReader(),
        )


@final
class LatestTpexDailyFeatureRepository(LatestFeatureRepository):
    """Read only exact-date TPEX feature-delta artifacts."""

    def __init__(self) -> None:
        super().__init__(
            market="TPEX",
            feature_names=TPEX_PRICE_VOLUME_FEATURE_NAMES,
            manifest_parser=daily_delta_manifest_from_object,
            reader=TpexDailyFeatureDeltaReader(),
            manifest_field="feature_delta_artifact_manifest",
            read_back_flag_field="feature_delta_artifact_read_back_verified",
        )


__all__ = [
    "LatestTpexFeatureCrossSection",
    "LatestTpexDailyFeatureRepository",
    "LatestTpexFeatureRepository",
    "LatestTpexFeatureSourceError",
]
