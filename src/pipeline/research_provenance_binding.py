"""Validate persisted research provenance against one model bundle."""

from __future__ import annotations

from collections.abc import Mapping
import re


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
_FEATURE_SOURCE_BINDINGS = (
    ("source_feature_run_id", "feature_source_run_id", _RUN_ID),
    ("source_feature_run_sha", "feature_source_run_sha", _GIT_SHA),
    ("source_feature_artifact_id", "feature_source_artifact_id", _RUN_ID),
    (
        "source_feature_artifact_digest",
        "feature_source_artifact_digest",
        _ARTIFACT_DIGEST,
    ),
)


def validate_research_run_provenance_binding(
    value: Mapping[str, object] | None,
    *,
    market: str,
    input_artifact_sha256: str,
    git_commit: str | None,
) -> None:
    """Reject incomplete or cross-artifact provenance at read and write time."""

    if value is None:
        if market == "TPEX":
            raise ValueError("TPEX bundle requires research_run_provenance")
        return
    prepared = value.get("prepared_artifact_manifest")
    if not isinstance(prepared, Mapping) or prepared.get("market") != market:
        raise ValueError("research run prepared provenance market is invalid")
    for field_name in _REQUIRED_PREPARED_HASHES:
        digest = prepared.get(field_name)
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise ValueError("research run prepared provenance is incomplete")
    if prepared.get("parquet_sha256") != input_artifact_sha256:
        raise ValueError("research run prepared Parquet hash does not match bundle")

    provenance_git = value.get("git_commit")
    if (
        not isinstance(provenance_git, str)
        or _GIT_SHA.fullmatch(provenance_git) is None
        or provenance_git != git_commit
    ):
        raise ValueError("research run Git commit does not match bundle")
    _validate_execution_source(value)
    if market == "TPEX":
        _validate_feature_source(value, prepared)


def _validate_execution_source(value: Mapping[str, object]) -> None:
    environment = value.get("execution_environment")
    git_source = value.get("git_commit_source")
    run_id = value.get("source_prepared_run_id")
    run_sha = value.get("source_prepared_run_sha")
    if environment == "GITHUB_ACTIONS":
        if (
            not isinstance(run_id, str)
            or _RUN_ID.fullmatch(run_id) is None
            or not isinstance(run_sha, str)
            or _GIT_SHA.fullmatch(run_sha) is None
            or git_source != "GITHUB_SHA"
        ):
            raise ValueError("research run workflow provenance is incomplete")
        return
    if (
        environment != "LOCAL"
        or git_source != "LOCAL_GIT_HEAD"
        or run_id is not None
        or run_sha is not None
    ):
        raise ValueError("local research run provenance is inconsistent")


def _validate_feature_source(
    value: Mapping[str, object],
    prepared: Mapping[object, object],
) -> None:
    for persisted_name, prepared_name, pattern in _FEATURE_SOURCE_BINDINGS:
        persisted = value.get(persisted_name)
        prepared_value = prepared.get(prepared_name)
        if (
            not isinstance(persisted, str)
            or pattern.fullmatch(persisted) is None
            or persisted != prepared_value
        ):
            raise ValueError("research run feature source provenance is incomplete")


__all__ = ["validate_research_run_provenance_binding"]
