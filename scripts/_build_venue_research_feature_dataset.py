"""Shared fail-closed CLI flow for venue-specific research feature artifacts."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from src.data.research.archive_feature_contracts import (
    combined_source_snapshot_hash,
)
from src.data.research.daily_bar_publication_snapshot import (
    DailyBarPublicationSnapshotReader,
    DailyBarPublicationSnapshotRepository,
)


@dataclass(frozen=True)
class VenueFeatureBuildDependencies:
    description: str
    market: str
    archive_scope_filters: Mapping[str, str]
    failure_reason_code: str
    supabase_writer_factory: Callable[..., Any]
    manifest_repository_factory: Callable[..., Any]
    identity_repository_factory: Callable[..., Any]
    r2_client_factory: Callable[..., Any]
    historical_reader_factory: Callable[..., Any]
    dataset_snapshot_hash: Callable[..., str]
    parquet_writer_factory: Callable[..., Any]
    dataset_builder_factory: Callable[..., Any]
    artifact_reader_factory: Callable[..., Any]


def _parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    _ = parser.add_argument("--output", required=True, type=Path)
    _ = parser.add_argument("--audit", required=True, type=Path)
    _ = parser.add_argument(
        "--include-current-publication",
        action="store_true",
        help="Merge the exact-date immutable current daily-bar publication.",
    )
    _ = parser.add_argument(
        "--required-as-of-date",
        type=date.fromisoformat,
        help="Fail unless the built feature artifact reaches this trading date.",
    )
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
    *,
    include_current_publication: bool,
    required_as_of_date: date | None,
) -> tuple[dict[str, object], Any]:
    source = dependencies.supabase_writer_factory(
        url=os.environ.get("SUPABASE_URL"),
        server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
    )
    manifests = cast(Any, dependencies.manifest_repository_factory(source)).fetch(
        filters=dependencies.archive_scope_filters
    )
    identities = cast(Any, dependencies.identity_repository_factory(source)).fetch()
    r2_client = dependencies.r2_client_factory()
    publication_snapshot = None
    if include_current_publication:
        if required_as_of_date is None:
            raise ValueError("required_as_of_date is required with current publication input")
        publication_manifest = DailyBarPublicationSnapshotRepository(source).fetch_exact(
            market=dependencies.market,
            trading_date=required_as_of_date,
        )
        publication_snapshot = DailyBarPublicationSnapshotReader(r2_client).read(
            publication_manifest
        )
    source_snapshot_sha256 = combined_source_snapshot_hash(
        historical_archive_snapshot_sha256=manifests.snapshot_sha256,
        publication_snapshot_sha256=(
            publication_snapshot.manifest.snapshot_sha256
            if publication_snapshot is not None
            else None
        ),
    )
    dataset_hash = dependencies.dataset_snapshot_hash(
        source_archive_snapshot_sha256=source_snapshot_sha256,
        current_identity_snapshot_sha256=identities.snapshot_sha256,
    )
    writer = dependencies.parquet_writer_factory(
        candidate_path,
        dataset_snapshot_sha256=dataset_hash,
        source_archive_snapshot_sha256=source_snapshot_sha256,
        current_identity_snapshot_sha256=identities.snapshot_sha256,
    )
    historical_reader = dependencies.historical_reader_factory(r2_client)
    audit = cast(Any, dependencies.dataset_builder_factory(historical_reader)).build(
        manifests=manifests,
        identities=identities,
        writer=writer,
        publication_snapshot=publication_snapshot,
    )
    artifact_reader = cast(Any, dependencies.artifact_reader_factory())
    artifact_manifest = artifact_reader.manifest_from_parquet(candidate_path)
    _ = artifact_reader.verify(candidate_path, artifact_manifest)
    payload = cast(dict[str, object], audit.as_json())
    if (
        required_as_of_date is not None
        and payload.get("latest_decision_date") != required_as_of_date.isoformat()
    ):
        raise ValueError(f"{dependencies.market}_REQUIRED_AS_OF_DATE_NOT_AVAILABLE")
    return payload, artifact_manifest


def run_feature_build(
    argv: Sequence[str] | None,
    dependencies: VenueFeatureBuildDependencies,
) -> int:
    arguments = _parser(dependencies.description).parse_args(argv)
    output_path = cast(Path, arguments.output)
    audit_path = cast(Path, arguments.audit)
    candidate_path = output_path.with_name(f".{output_path.name}.{uuid4().hex}.candidate")
    try:
        payload, artifact_manifest = _build_candidate(
            candidate_path,
            dependencies,
            include_current_publication=cast(bool, arguments.include_current_publication),
            required_as_of_date=cast(date | None, arguments.required_as_of_date),
        )
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
            "reason_codes": [getattr(error, "reason_code", dependencies.failure_reason_code)],
        }
        _write_json(audit_path, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1
