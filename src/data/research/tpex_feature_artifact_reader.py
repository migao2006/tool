"""TPEX feature artifact read-back verifier."""

from typing import final

from .feature_artifact_reader import FeatureArtifactReader
from .tpex_feature_artifact_contracts import (
    TpexFeatureArtifactManifest,
    VerifiedTpexFeatureArtifact,
)


@final
class TpexFeatureArtifactReader(
    FeatureArtifactReader[
        TpexFeatureArtifactManifest,
        VerifiedTpexFeatureArtifact,
    ]
):
    def __init__(self) -> None:
        super().__init__(
            market="TPEX",
            manifest_type=TpexFeatureArtifactManifest,
            verified_type=VerifiedTpexFeatureArtifact,
        )


__all__ = ["TpexFeatureArtifactReader"]
