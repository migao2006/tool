"""Trace one research run to its verified prepared input and Git revision."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
from typing import cast

from .contracts import PipelineBatch


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID = re.compile(r"^[1-9][0-9]*$")
_ARTIFACT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUIRED_PREPARED_HASHES = (
    "parquet_sha256",
    "prepared_dataset_snapshot_sha256",
    "daily_archive_snapshot_sha256",
    "current_identity_snapshot_sha256",
    "feature_artifact_sha256",
    "calendar_snapshot_sha256",
    "source_hash",
    "benchmark_snapshot_sha256",
    "feature_schema_hash",
)


class ResearchRunProvenanceError(ValueError):
    """Stable failure raised when a research run cannot be reproduced."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code: str = reason_code


@dataclass(frozen=True)
class ResearchRunProvenance:
    prepared_artifact_manifest: Mapping[str, object]
    git_commit: str
    git_commit_source: str
    execution_environment: str
    source_prepared_run_id: str | None
    source_prepared_run_sha: str | None
    source_feature_run_id: str | None
    source_feature_run_sha: str | None
    source_feature_artifact_id: str | None
    source_feature_artifact_digest: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_environment": self.execution_environment,
            "git_commit": self.git_commit,
            "git_commit_source": self.git_commit_source,
            "prepared_artifact_manifest": dict(self.prepared_artifact_manifest),
            "source_prepared_run_id": self.source_prepared_run_id,
            "source_prepared_run_sha": self.source_prepared_run_sha,
            "source_feature_run_id": self.source_feature_run_id,
            "source_feature_run_sha": self.source_feature_run_sha,
            "source_feature_artifact_id": self.source_feature_artifact_id,
            "source_feature_artifact_digest": self.source_feature_artifact_digest,
        }


def _git_identity() -> tuple[str, str]:
    github_sha = os.environ.get("GITHUB_SHA", "").strip().lower()
    if github_sha:
        if _GIT_SHA.fullmatch(github_sha) is None:
            raise ResearchRunProvenanceError(
                "GIT_COMMIT_INVALID",
                "GITHUB_SHA is not a full lowercase Git commit",
            )
        return github_sha, "GITHUB_SHA"
    project_root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    local_sha = completed.stdout.strip().lower()
    if completed.returncode != 0 or _GIT_SHA.fullmatch(local_sha) is None:
        raise ResearchRunProvenanceError(
            "GIT_COMMIT_UNAVAILABLE",
            "The local research run is not attached to a Git commit",
        )
    return local_sha, "LOCAL_GIT_HEAD"


def _source_run_identity() -> tuple[str | None, str | None, str]:
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() != "true":
        return None, None, "LOCAL"
    run_id = os.environ.get("TPEX_PREPARED_SOURCE_RUN_ID", "").strip()
    run_sha = os.environ.get("TPEX_PREPARED_SOURCE_RUN_SHA", "").strip().lower()
    if _RUN_ID.fullmatch(run_id) is None or _GIT_SHA.fullmatch(run_sha) is None:
        raise ResearchRunProvenanceError(
            "PREPARED_SOURCE_RUN_PROVENANCE_MISSING",
            "GitHub research runs require a verified prepared source run",
        )
    return run_id, run_sha, "GITHUB_ACTIONS"


def _feature_source_identity(
    manifest: Mapping[str, object],
    *,
    required: bool,
) -> tuple[str | None, str | None, str | None, str | None]:
    run_id = manifest.get("feature_source_run_id")
    run_sha = manifest.get("feature_source_run_sha")
    artifact_id = manifest.get("feature_source_artifact_id")
    artifact_digest = manifest.get("feature_source_artifact_digest")
    if run_id is None and run_sha is None and artifact_id is None:
        if required:
            raise ResearchRunProvenanceError(
                "PREPARED_FEATURE_SOURCE_PROVENANCE_MISSING",
                "TPEX research requires a trusted feature workflow source",
            )
        return None, None, None, None
    if required and artifact_digest is None:
        raise ResearchRunProvenanceError(
            "PREPARED_FEATURE_SOURCE_PROVENANCE_MISSING",
            "TPEX research requires the feature artifact digest",
        )
    if (
        not isinstance(run_id, str)
        or _RUN_ID.fullmatch(run_id) is None
        or not isinstance(run_sha, str)
        or _GIT_SHA.fullmatch(run_sha) is None
        or not isinstance(artifact_id, str)
        or _RUN_ID.fullmatch(artifact_id) is None
        or (
            artifact_digest is not None
            and (
                not isinstance(artifact_digest, str)
                or _ARTIFACT_DIGEST.fullmatch(artifact_digest) is None
            )
        )
    ):
        raise ResearchRunProvenanceError(
            "PREPARED_FEATURE_SOURCE_PROVENANCE_INVALID",
            "Prepared feature workflow source provenance is invalid",
        )
    return run_id, run_sha, artifact_id, artifact_digest


def research_run_provenance(
    batch: PipelineBatch,
    *,
    expected_market: str,
) -> ResearchRunProvenance:
    raw_manifest = batch.source_metadata.get("prepared_artifact_manifest")
    if not isinstance(raw_manifest, Mapping):
        raise ResearchRunProvenanceError(
            "PREPARED_ARTIFACT_PROVENANCE_MISSING",
            "The prepared artifact manifest was not retained by the repository",
        )
    manifest = cast(Mapping[str, object], raw_manifest)
    market = manifest.get("market")
    if market != expected_market:
        raise ResearchRunProvenanceError(
            "PREPARED_ARTIFACT_PROVENANCE_MISMATCH",
            "Prepared artifact market does not match the research venue",
        )
    if any(
        not isinstance(manifest.get(name), str)
        or _SHA256.fullmatch(cast(str, manifest[name])) is None
        for name in _REQUIRED_PREPARED_HASHES
    ):
        raise ResearchRunProvenanceError(
            "PREPARED_ARTIFACT_PROVENANCE_INCOMPLETE",
            "Prepared artifact snapshot hashes are incomplete",
        )
    if batch.source_hash != manifest["parquet_sha256"]:
        raise ResearchRunProvenanceError(
            "PREPARED_ARTIFACT_PROVENANCE_MISMATCH",
            "Pipeline source hash does not match the prepared Parquet manifest",
        )
    (
        feature_run_id,
        feature_run_sha,
        feature_artifact_id,
        feature_artifact_digest,
    ) = _feature_source_identity(
        manifest,
        required=expected_market == "TPEX",
    )
    git_commit, git_source = _git_identity()
    source_run_id, source_run_sha, environment = _source_run_identity()
    return ResearchRunProvenance(
        prepared_artifact_manifest=dict(manifest),
        git_commit=git_commit,
        git_commit_source=git_source,
        execution_environment=environment,
        source_prepared_run_id=source_run_id,
        source_prepared_run_sha=source_run_sha,
        source_feature_run_id=feature_run_id,
        source_feature_run_sha=feature_run_sha,
        source_feature_artifact_id=feature_artifact_id,
        source_feature_artifact_digest=feature_artifact_digest,
    )


__all__ = [
    "ResearchRunProvenance",
    "ResearchRunProvenanceError",
    "research_run_provenance",
]
