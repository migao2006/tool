"""TPEX latest feature reader with an exact market boundary."""

from __future__ import annotations

from typing import final

from src.data.research.tpex_feature_artifact_contracts import manifest_from_object
from src.data.research.tpex_feature_artifact_reader import TpexFeatureArtifactReader
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


__all__ = [
    "LatestTpexFeatureCrossSection",
    "LatestTpexFeatureRepository",
    "LatestTpexFeatureSourceError",
]
