"""Shared fail-closed CLI flow for venue-specific research feature artifacts."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, cast
from uuid import uuid4


@dataclass(frozen=True)
class VenueFeatureBuildDependencies:
    description: str
    archive_scope_filters: Mapping[str, str]
    failure_reason_code: str
    supabase_writer_factory: Callable[..., object]
    manifest_repository_factory: Callable[[object], object]
    identity_repository_factory: Callable[[object], object]
    r2_client_factory: Callable[[], object]
    historical_reader_factory: Callable[[object], object]
    dataset_snapshot_hash: Callable[..., str]
    parquet_writer_factory: Callable[..., object]
    dataset_builder_factory: Callable[[object], object]
    artifact_reader_factory: Callable[[], object]


def _parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    _ = parser.add_argument("--output", required=True, type=Path)
    _ = parser.add_argument("--audit", required=True, type=Path)
    return parser


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    _ = temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _ = temporary.replace(path)


def _build_candidate(
    candidate_path: Path,
    dependencies: VenueFeatureBuildDependencies,
) -> tuple[dict[str, object], object]:
    source = dependencies.supabase_writer_factory(
        url=os.environ.get("SUPABASE_URL"),
        server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
    )
    manifests = cast(Any, dependencies.manifest_repository_factory(source)).fetch(
        filters=dependencies.archive_scope_filters
    )
    identities = cast(Any, dependencies.identity_repository_factory(source)).fetch()
    dataset_hash = dependencies.dataset_snapshot_hash(
        source_archive_snapshot_sha256=manifests.snapshot_sha256,
        current_identity_snapshot_sha256=identities.snapshot_sha256,
    )
    writer = dependencies.parquet_writer_factory(
        candidate_path,
        dataset_snapshot_sha256=dataset_hash,
        source_archive_snapshot_sha256=manifests.snapshot_sha256,
        current_identity_snapshot_sha256=identities.snapshot_sha256,
    )
    historical_reader = dependencies.historical_reader_factory(
        dependencies.r2_client_factory()
    )
    audit = cast(Any, dependencies.dataset_builder_factory(historical_reader)).build(
        manifests=manifests,
        identities=identities,
        writer=writer,
    )
    artifact_reader = cast(Any, dependencies.artifact_reader_factory())
    artifact_manifest = artifact_reader.manifest_from_parquet(candidate_path)
    _ = artifact_reader.verify(candidate_path, artifact_manifest)
    return cast(dict[str, object], audit.as_json()), artifact_manifest


def run_feature_build(
    argv: Sequence[str] | None,
    dependencies: VenueFeatureBuildDependencies,
) -> int:
    arguments = _parser(dependencies.description).parse_args(argv)
    output_path = cast(Path, arguments.output)
    audit_path = cast(Path, arguments.audit)
    candidate_path = output_path.with_name(
        f".{output_path.name}.{uuid4().hex}.candidate"
    )
    try:
        payload, artifact_manifest = _build_candidate(candidate_path, dependencies)
        _ = candidate_path.replace(output_path)
        payload["output_file"] = output_path.name
        payload["feature_artifact_manifest"] = artifact_manifest.to_dict()
        payload["feature_artifact_read_back_verified"] = True
        _write_json(audit_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as error:  # fail closed at the CLI boundary
        candidate_path.unlink(missing_ok=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "build_status": "FAIL",
            "system_status": "FAIL",
            "usage_scope": "FEATURE_RESEARCH_ONLY",
            "label_status": "LABELS_NOT_ASSEMBLED",
            "reason_codes": [
                getattr(error, "reason_code", dependencies.failure_reason_code)
            ],
        }
        _write_json(audit_path, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1
