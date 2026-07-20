"""Typed provenance contracts for one TWSE research feature artifact."""

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


TWSE_FEATURE_ARTIFACT_MANIFEST_VERSION = "twse-feature-artifact-manifest.v1"
TWSE_FEATURE_ARTIFACT_USAGE_SCOPE = FEATURE_ARTIFACT_USAGE_SCOPE
TWSE_FEATURE_ARTIFACT_SYSTEM_STATUS = FEATURE_ARTIFACT_SYSTEM_STATUS
TWSE_FEATURE_ARTIFACT_LABEL_STATUS = FEATURE_ARTIFACT_LABEL_STATUS
TWSE_FEATURE_ARTIFACT_AVAILABILITY_MODE = FEATURE_ARTIFACT_AVAILABILITY_MODE
TwseFeatureArtifactReadError = FeatureArtifactReadError


@dataclass(frozen=True)
class TwseFeatureArtifactManifest(FeatureArtifactManifest):
    MARKET: ClassVar[str] = "TWSE"
    MANIFEST_VERSION: ClassVar[str] = TWSE_FEATURE_ARTIFACT_MANIFEST_VERSION

    manifest_version: str = TWSE_FEATURE_ARTIFACT_MANIFEST_VERSION


class VerifiedTwseFeatureArtifact(VerifiedFeatureArtifact):
    MARKET: ClassVar[str] = "TWSE"

    manifest: TwseFeatureArtifactManifest


def manifest_from_object(value: object) -> TwseFeatureArtifactManifest:
    return cast(
        TwseFeatureArtifactManifest,
        typed_manifest_from_object(value, TwseFeatureArtifactManifest),
    )


__all__ = [
    "TWSE_FEATURE_ARTIFACT_MANIFEST_VERSION",
    "TwseFeatureArtifactManifest",
    "TwseFeatureArtifactReadError",
    "VerifiedTwseFeatureArtifact",
    "manifest_from_object",
]
