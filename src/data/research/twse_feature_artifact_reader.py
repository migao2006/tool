"""Backward-compatible TWSE feature artifact read-back verifier."""

from typing import final

from .feature_artifact_reader import FeatureArtifactReader
from .twse_feature_artifact_contracts import (
    TwseFeatureArtifactManifest,
    VerifiedTwseFeatureArtifact,
)


@final
class TwseFeatureArtifactReader(
    FeatureArtifactReader[
        TwseFeatureArtifactManifest,
        VerifiedTwseFeatureArtifact,
    ]
):
    def __init__(self) -> None:
        super().__init__(
            market="TWSE",
            manifest_type=TwseFeatureArtifactManifest,
            verified_type=VerifiedTwseFeatureArtifact,
        )


__all__ = ["TwseFeatureArtifactReader"]
