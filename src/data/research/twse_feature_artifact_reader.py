"""Derive and verify TWSE feature artifact provenance from Parquet read-back."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, final

from .twse_feature_artifact_contracts import (
    TwseFeatureArtifactManifest,
    TwseFeatureArtifactReadError,
    VerifiedTwseFeatureArtifact,
    _verified_artifact,  # pyright: ignore[reportPrivateUsage]
)
from .twse_feature_artifact_validation import (
    metadata_from_schema,
    schema_digest,
    validate_metadata,
    validate_rows,
    validate_schema,
)


def _modules() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ModuleNotFoundError as error:
        raise TwseFeatureArtifactReadError(
            "PARQUET_DEPENDENCY_MISSING",
            "pyarrow is required to verify TWSE feature artifacts",
        ) from error
    return pa, pq


def _digest_file(path: Path) -> tuple[str, int]:
    digest = sha256()
    byte_size = 0
    try:
        with path.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
                byte_size += len(block)
    except OSError as error:
        raise TwseFeatureArtifactReadError(
            "TWSE_FEATURE_ARTIFACT_READ_FAILED",
            "Unable to read the TWSE feature artifact",
        ) from error
    if byte_size <= 0:
        raise TwseFeatureArtifactReadError(
            "TWSE_FEATURE_ARTIFACT_EMPTY",
            "The TWSE feature artifact is empty",
        )
    return digest.hexdigest(), byte_size


def _open_parquet(path: Path) -> Any:
    _, pq = _modules()
    try:
        return pq.ParquetFile(path)
    except Exception as error:
        raise TwseFeatureArtifactReadError(
            "TWSE_FEATURE_ARTIFACT_PARQUET_INVALID",
            "TWSE feature artifact is not readable Parquet",
        ) from error


def _typed_manifest(value: object) -> TwseFeatureArtifactManifest:
    if not isinstance(value, TwseFeatureArtifactManifest):
        raise TypeError("a typed TWSE feature artifact manifest is required")
    return value


def _verified_input(value: object) -> VerifiedTwseFeatureArtifact:
    if not isinstance(value, VerifiedTwseFeatureArtifact):
        raise TypeError("a verified TWSE feature artifact is required")
    return value


@final
class TwseFeatureArtifactReader:
    """Build a sidecar manifest, then verify later bytes against that manifest."""

    def manifest_from_parquet(self, path: str | Path) -> TwseFeatureArtifactManifest:
        artifact_path = Path(path)
        parquet_sha256, byte_size = _digest_file(artifact_path)
        parquet = _open_parquet(artifact_path)
        row_count = parquet.metadata.num_rows
        if row_count <= 0:
            raise TwseFeatureArtifactReadError(
                "TWSE_FEATURE_ARTIFACT_ROWS_EMPTY",
                "TWSE feature artifact must contain at least one row",
            )
        values = metadata_from_schema(parquet.schema_arrow)
        validate_metadata(values)
        validate_schema(parquet.schema_arrow, values)
        validate_rows(parquet, values)
        return TwseFeatureArtifactManifest(
            parquet_sha256=parquet_sha256,
            parquet_schema_sha256=schema_digest(parquet.schema_arrow),
            byte_size=byte_size,
            row_count=row_count,
            dataset_version=values["dataset_version"],
            dataset_snapshot_sha256=values["dataset_snapshot_sha256"],
            source_archive_snapshot_sha256=values["source_archive_snapshot_sha256"],
            current_identity_snapshot_sha256=values["current_identity_snapshot_sha256"],
            feature_schema_version=values["feature_schema_version"],
            feature_schema_hash=values["feature_schema_hash"],
            decision_time_policy_version=values["decision_time_policy_version"],
            availability_mode=values["availability_mode"],
            horizon=int(values["horizon"]),
            label_status=values["label_status"],
            usage_scope=values["usage_scope"],
            system_status=values["system_status"],
            point_in_time_status="UNVERIFIED",
        )

    def verify(
        self,
        path: str | Path,
        manifest: TwseFeatureArtifactManifest,
    ) -> VerifiedTwseFeatureArtifact:
        typed_manifest = _typed_manifest(manifest)
        artifact_path = Path(path)
        observed = self.manifest_from_parquet(artifact_path)
        if observed != typed_manifest:
            raise TwseFeatureArtifactReadError(
                "TWSE_FEATURE_ARTIFACT_MANIFEST_MISMATCH",
                "TWSE feature artifact bytes do not match the persisted manifest",
            )
        return _verified_artifact(artifact_path, observed)

    def read_table(self, artifact: VerifiedTwseFeatureArtifact) -> Any:
        """Re-verify immutable identity before releasing rows downstream."""

        verified = _verified_input(artifact)
        observed = self.manifest_from_parquet(verified.path)
        if observed != verified.manifest:
            raise TwseFeatureArtifactReadError(
                "TWSE_FEATURE_ARTIFACT_CHANGED_AFTER_VERIFICATION",
                "TWSE feature artifact changed after read-back verification",
            )
        return _open_parquet(verified.path).read()


__all__ = ["TwseFeatureArtifactReader"]
