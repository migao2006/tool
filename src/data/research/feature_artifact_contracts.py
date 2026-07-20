"""Market-neutral typed contracts for research feature artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import ClassVar, Self, cast

from .archive_feature_market import archive_feature_market_profile


FEATURE_ARTIFACT_USAGE_SCOPE = "FEATURE_RESEARCH_ONLY"
FEATURE_ARTIFACT_SYSTEM_STATUS = "RESEARCH_ONLY"
FEATURE_ARTIFACT_LABEL_STATUS = "LABELS_NOT_ASSEMBLED"
FEATURE_ARTIFACT_AVAILABILITY_MODE = "RESEARCH_SCHEDULING_HINT"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class FeatureArtifactReadError(RuntimeError):
    """Stable fail-closed error without paths, row values, or credentials."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code: str = reason_code


def artifact_error(market: str, suffix: str, message: str) -> FeatureArtifactReadError:
    return FeatureArtifactReadError(f"{market}_FEATURE_ARTIFACT_{suffix}", message)


def _required_text(values: Mapping[str, object], name: str) -> str:
    value = values.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"feature artifact manifest is missing {name}")
    return value.strip()


def _positive_integer(values: Mapping[str, object], name: str) -> int:
    value = values.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"feature artifact manifest contains invalid {name}")
    return value


@dataclass(frozen=True)
class FeatureArtifactManifest:
    """Meaning-bearing digest and lineage derived from a Parquet read-back."""

    MARKET: ClassVar[str]
    MANIFEST_VERSION: ClassVar[str]

    parquet_sha256: str
    parquet_schema_sha256: str
    byte_size: int
    row_count: int
    dataset_version: str
    dataset_snapshot_sha256: str
    source_archive_snapshot_sha256: str
    current_identity_snapshot_sha256: str
    feature_schema_version: str
    feature_schema_hash: str
    decision_time_policy_version: str
    availability_mode: str
    horizon: int
    label_status: str
    usage_scope: str
    system_status: str
    point_in_time_status: str
    manifest_version: str

    def __post_init__(self) -> None:
        profile = archive_feature_market_profile(self.MARKET)
        digests = (
            self.parquet_sha256,
            self.parquet_schema_sha256,
            self.dataset_snapshot_sha256,
            self.source_archive_snapshot_sha256,
            self.current_identity_snapshot_sha256,
            self.feature_schema_hash,
        )
        if any(_SHA256.fullmatch(value) is None for value in digests):
            raise ValueError("feature artifact manifest contains an invalid SHA-256")
        if self.byte_size <= 0 or self.row_count <= 0:
            raise ValueError("feature artifact byte and row counts must be positive")
        expected = (
            self.manifest_version == self.MANIFEST_VERSION
            and self.dataset_version == profile.dataset_version
            and self.feature_schema_version == profile.feature.schema_version
            and self.feature_schema_hash == profile.feature.schema_hash
            and self.decision_time_policy_version
            == profile.decision_time_policy_version
            and self.availability_mode == FEATURE_ARTIFACT_AVAILABILITY_MODE
            and self.horizon == 5
            and self.label_status == FEATURE_ARTIFACT_LABEL_STATUS
            and self.usage_scope == FEATURE_ARTIFACT_USAGE_SCOPE
            and self.system_status == FEATURE_ARTIFACT_SYSTEM_STATUS
            and self.point_in_time_status == "UNVERIFIED"
        )
        if not expected:
            raise ValueError(
                "feature artifact exceeds the frozen research-only contract"
            )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> Self:
        """Parse a persisted sidecar without accepting implicit defaults."""

        try:
            return cls(
                manifest_version=_required_text(values, "manifest_version"),
                parquet_sha256=_required_text(values, "parquet_sha256").lower(),
                parquet_schema_sha256=_required_text(
                    values, "parquet_schema_sha256"
                ).lower(),
                byte_size=_positive_integer(values, "byte_size"),
                row_count=_positive_integer(values, "row_count"),
                dataset_version=_required_text(values, "dataset_version"),
                dataset_snapshot_sha256=_required_text(
                    values, "dataset_snapshot_sha256"
                ).lower(),
                source_archive_snapshot_sha256=_required_text(
                    values, "source_archive_snapshot_sha256"
                ).lower(),
                current_identity_snapshot_sha256=_required_text(
                    values, "current_identity_snapshot_sha256"
                ).lower(),
                feature_schema_version=_required_text(values, "feature_schema_version"),
                feature_schema_hash=_required_text(
                    values, "feature_schema_hash"
                ).lower(),
                decision_time_policy_version=_required_text(
                    values, "decision_time_policy_version"
                ),
                availability_mode=_required_text(values, "availability_mode"),
                horizon=_positive_integer(values, "horizon"),
                label_status=_required_text(values, "label_status"),
                usage_scope=_required_text(values, "usage_scope"),
                system_status=_required_text(values, "system_status"),
                point_in_time_status=_required_text(values, "point_in_time_status"),
            )
        except (TypeError, ValueError) as error:
            raise artifact_error(
                cls.MARKET,
                "MANIFEST_INVALID",
                f"The {cls.MARKET} feature artifact manifest is incomplete or inconsistent",
            ) from error


_VERIFIED_ARTIFACT_PROOFS = {market: object() for market in ("TWSE", "TPEX")}


@dataclass(frozen=True, init=False)
class VerifiedFeatureArtifact:
    """Opaque proof that bytes, schema, metadata, rows, and manifest agree."""

    MARKET: ClassVar[str]

    path: Path
    manifest: FeatureArtifactManifest
    _proof: object

    def __init__(
        self,
        *,
        path: Path,
        manifest: FeatureArtifactManifest,
        _proof: object,
    ) -> None:
        if (
            _proof is not _VERIFIED_ARTIFACT_PROOFS.get(self.MARKET)
            or manifest.MARKET != self.MARKET
        ):
            raise TypeError(
                "verified feature artifacts can only be created by matching read-back"
            )
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "manifest", manifest)
        object.__setattr__(self, "_proof", _proof)

    @property
    def point_in_time_verified(self) -> bool:
        """This artifact version is structurally verified but never PIT-promoted."""

        return False


def verified_artifact(
    artifact_type: type[VerifiedFeatureArtifact],
    path: Path,
    manifest: FeatureArtifactManifest,
) -> VerifiedFeatureArtifact:
    market = artifact_type.MARKET
    return artifact_type(
        path=path,
        manifest=manifest,
        _proof=_VERIFIED_ARTIFACT_PROOFS[market],
    )


def typed_manifest_from_object(
    value: object,
    manifest_type: type[FeatureArtifactManifest],
) -> FeatureArtifactManifest:
    if isinstance(value, manifest_type):
        return value
    if not isinstance(value, Mapping):
        raise artifact_error(
            manifest_type.MARKET,
            "MANIFEST_INVALID",
            f"A typed {manifest_type.MARKET} feature artifact manifest is required",
        )
    return manifest_type.from_mapping(cast(Mapping[str, object], value))


__all__ = [
    "FEATURE_ARTIFACT_AVAILABILITY_MODE",
    "FEATURE_ARTIFACT_LABEL_STATUS",
    "FEATURE_ARTIFACT_SYSTEM_STATUS",
    "FEATURE_ARTIFACT_USAGE_SCOPE",
    "FeatureArtifactManifest",
    "FeatureArtifactReadError",
    "VerifiedFeatureArtifact",
    "artifact_error",
    "typed_manifest_from_object",
    "verified_artifact",
]
