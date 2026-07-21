"""Read-back verification shared by venue-specific feature artifacts."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Generic, TypeVar, cast

from .feature_artifact_contracts import (
    FeatureArtifactManifest,
    VerifiedFeatureArtifact,
    artifact_error,
    verified_artifact,
)
from .feature_artifact_validation import (
    metadata_from_schema,
    schema_digest,
    validate_metadata,
    validate_rows,
    validate_schema,
)


ManifestT = TypeVar("ManifestT", bound=FeatureArtifactManifest)
VerifiedT = TypeVar("VerifiedT", bound=VerifiedFeatureArtifact)


def _modules() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ModuleNotFoundError as error:
        from .feature_artifact_contracts import FeatureArtifactReadError

        raise FeatureArtifactReadError(
            "PARQUET_DEPENDENCY_MISSING",
            "pyarrow is required to verify feature artifacts",
        ) from error
    return pa, pq


class FeatureArtifactReader(Generic[ManifestT, VerifiedT]):
    """Build a sidecar manifest, then verify later bytes against it."""

    def __init__(
        self,
        *,
        market: str,
        manifest_type: type[ManifestT],
        verified_type: type[VerifiedT],
    ) -> None:
        if manifest_type.MARKET != market or verified_type.MARKET != market:
            raise ValueError("feature artifact reader types do not match its market")
        self._market: str = market
        self._manifest_type: type[ManifestT] = manifest_type
        self._verified_type: type[VerifiedT] = verified_type

    def _digest_file(self, path: Path) -> tuple[str, int]:
        digest = sha256()
        byte_size = 0
        try:
            with path.open("rb") as source:
                while block := source.read(1024 * 1024):
                    digest.update(block)
                    byte_size += len(block)
        except OSError as error:
            raise artifact_error(
                self._market,
                "READ_FAILED",
                f"Unable to read the {self._market} feature artifact",
            ) from error
        if byte_size <= 0:
            raise artifact_error(
                self._market,
                "EMPTY",
                f"The {self._market} feature artifact is empty",
            )
        return digest.hexdigest(), byte_size

    def _open_parquet(self, path: Path) -> Any:
        _, pq = _modules()
        try:
            return pq.ParquetFile(path)
        except Exception as error:
            raise artifact_error(
                self._market,
                "PARQUET_INVALID",
                f"{self._market} feature artifact is not readable Parquet",
            ) from error

    def manifest_from_parquet(self, path: str | Path) -> ManifestT:
        artifact_path = Path(path)
        parquet_sha256, byte_size = self._digest_file(artifact_path)
        parquet = self._open_parquet(artifact_path)
        row_count = parquet.metadata.num_rows
        if row_count <= 0:
            raise artifact_error(
                self._market,
                "ROWS_EMPTY",
                f"{self._market} feature artifact must contain at least one row",
            )
        values = metadata_from_schema(parquet.schema_arrow, market=self._market)
        validate_metadata(values, market=self._market)
        validate_schema(parquet.schema_arrow, values, market=self._market)
        validate_rows(parquet, values, market=self._market)
        return self._manifest_type(
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
            manifest_version=self._manifest_type.MANIFEST_VERSION,
        )

    def verify(self, path: str | Path, manifest: ManifestT) -> VerifiedT:
        if not isinstance(manifest, self._manifest_type):
            raise TypeError(
                f"a typed {self._market} feature artifact manifest is required"
            )
        artifact_path = Path(path)
        observed = self.manifest_from_parquet(artifact_path)
        if observed != manifest:
            raise artifact_error(
                self._market,
                "MANIFEST_MISMATCH",
                f"{self._market} feature artifact bytes do not match the manifest",
            )
        return cast(
            VerifiedT,
            verified_artifact(self._verified_type, artifact_path, observed),
        )

    def read_table(self, artifact: VerifiedT) -> Any:
        """Re-verify immutable identity before releasing rows downstream."""

        if not isinstance(artifact, self._verified_type):
            raise TypeError(f"a verified {self._market} feature artifact is required")
        observed = self.manifest_from_parquet(artifact.path)
        if observed != artifact.manifest:
            raise artifact_error(
                self._market,
                "CHANGED_AFTER_VERIFICATION",
                f"{self._market} feature artifact changed after verification",
            )
        return self._open_parquet(artifact.path).read()


__all__ = ["FeatureArtifactReader"]
