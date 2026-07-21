"""TWSE compatibility wrapper for the venue-scoped latest feature reader."""

from __future__ import annotations

from typing import final

from src.data.research.twse_feature_artifact_contracts import manifest_from_object
from src.data.research.twse_feature_artifact_reader import TwseFeatureArtifactReader
from src.features.twse_price_volume_schema import TWSE_PRICE_VOLUME_FEATURE_NAMES

from .venue_latest_feature_repository import (
    LatestFeatureCrossSection,
    LatestFeatureRepository,
    LatestFeatureSourceError,
)


LatestTwseFeatureCrossSection = LatestFeatureCrossSection
LatestTwseFeatureSourceError = LatestFeatureSourceError


@final
class LatestTwseFeatureRepository(LatestFeatureRepository):
    def __init__(self) -> None:
        super().__init__(
            market="TWSE",
            feature_names=TWSE_PRICE_VOLUME_FEATURE_NAMES,
            manifest_parser=manifest_from_object,
            reader=TwseFeatureArtifactReader(),
        )


__all__ = [
    "LatestTwseFeatureCrossSection",
    "LatestTwseFeatureRepository",
    "LatestTwseFeatureSourceError",
]
