"""Typed provenance contracts for one TPEX research feature artifact."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, cast

from .feature_artifact_contracts import (
    FEATURE_ARTIFACT_AVAILABILITY_MODE,
    FEATURE_ARTIFACT_LABEL_STATUS,
    FEATURE_ARTIFACT_SYSTEM_STATUS,
    FEATURE_ARTIFACT_USAGE_SCOPE,
    FeatureArtifactManifest,
    FeatureArtifactReadError,
    VerifiedFeatureArtifact,
    typed_manifest_from_object,
)


TPEX_FEATURE_ARTIFACT_MANIFEST_VERSION = "tpex-feature-artifact-manifest.v1"
TPEX_FEATURE_ARTIFACT_USAGE_SCOPE = FEATURE_ARTIFACT_USAGE_SCOPE
TPEX_FEATURE_ARTIFACT_SYSTEM_STATUS = FEATURE_ARTIFACT_SYSTEM_STATUS
TPEX_FEATURE_ARTIFACT_LABEL_STATUS = FEATURE_ARTIFACT_LABEL_STATUS
TPEX_FEATURE_ARTIFACT_AVAILABILITY_MODE = FEATURE_ARTIFACT_AVAILABILITY_MODE
TpexFeatureArtifactReadError = FeatureArtifactReadError


@dataclass(frozen=True)
class TpexFeatureArtifactManifest(FeatureArtifactManifest):
    MARKET: ClassVar[str] = "TPEX"
    MANIFEST_VERSION: ClassVar[str] = TPEX_FEATURE_ARTIFACT_MANIFEST_VERSION

    manifest_version: str = TPEX_FEATURE_ARTIFACT_MANIFEST_VERSION


class VerifiedTpexFeatureArtifact(VerifiedFeatureArtifact):
    MARKET: ClassVar[str] = "TPEX"

    manifest: TpexFeatureArtifactManifest


def manifest_from_object(value: object) -> TpexFeatureArtifactManifest:
    return cast(
        TpexFeatureArtifactManifest,
        typed_manifest_from_object(value, TpexFeatureArtifactManifest),
    )


__all__ = [
    "TPEX_FEATURE_ARTIFACT_MANIFEST_VERSION",
    "TpexFeatureArtifactManifest",
    "TpexFeatureArtifactReadError",
    "VerifiedTpexFeatureArtifact",
    "manifest_from_object",
]
