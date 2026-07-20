"""Build a feature-only TPEX common-stock research dataset."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import cast
from uuid import uuid4

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root  # pyright: ignore[reportImplicitRelativeImport]

add_project_root()

from src.data.archive.historical_parquet_reader import HistoricalParquetReader  # noqa: E402
from src.data.archive.manifest_repository import (  # noqa: E402
    HistoricalArchiveManifestRepository,
)
from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402
from src.data.object_storage.r2_client import R2Client  # noqa: E402
from src.data.research.tpex_archive_feature_builder import (  # noqa: E402
    TpexArchiveFeatureDatasetBuilder,
)
from src.data.research.tpex_archive_feature_contracts import (  # noqa: E402
    TPEX_ARCHIVE_SCOPE_FILTERS,
    dataset_snapshot_hash,
)
from src.data.research.tpex_archive_feature_parquet import (  # noqa: E402
    TpexArchiveFeatureParquetWriter,
)
from src.data.research.tpex_current_identity_repository import (  # noqa: E402
    TpexCurrentIdentityRepository,
)
from src.data.research.tpex_feature_artifact_reader import (  # noqa: E402
    TpexFeatureArtifactReader,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Stream fully verified TPEX common-stock daily-bar archives into a "
            "RESEARCH_ONLY price/volume feature dataset."
        )
    )
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


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    output_path = cast(Path, arguments.output)
    audit_path = cast(Path, arguments.audit)
    candidate_path = output_path.with_name(
        f".{output_path.name}.{uuid4().hex}.candidate"
    )
    try:
        source = SupabaseWriter(
            url=os.environ.get("SUPABASE_URL"),
            server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        )
        manifests = HistoricalArchiveManifestRepository(source).fetch(
            filters=TPEX_ARCHIVE_SCOPE_FILTERS
        )
        identities = TpexCurrentIdentityRepository(source).fetch()
        dataset_hash = dataset_snapshot_hash(
            source_archive_snapshot_sha256=manifests.snapshot_sha256,
            current_identity_snapshot_sha256=identities.snapshot_sha256,
        )
        writer = TpexArchiveFeatureParquetWriter(
            candidate_path,
            dataset_snapshot_sha256=dataset_hash,
            source_archive_snapshot_sha256=manifests.snapshot_sha256,
            current_identity_snapshot_sha256=identities.snapshot_sha256,
        )
        audit = TpexArchiveFeatureDatasetBuilder(
            HistoricalParquetReader(R2Client.from_env())
        ).build(
            manifests=manifests,
            identities=identities,
            writer=writer,
        )
        artifact_reader = TpexFeatureArtifactReader()
        artifact_manifest = artifact_reader.manifest_from_parquet(candidate_path)
        _ = artifact_reader.verify(candidate_path, artifact_manifest)
        _ = candidate_path.replace(output_path)
        payload = audit.as_json()
        payload["output_file"] = output_path.name
        payload["feature_artifact_manifest"] = artifact_manifest.to_dict()
        payload["feature_artifact_read_back_verified"] = True
        _write_json(audit_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as error:  # fail closed at the CLI boundary
        candidate_path.unlink(missing_ok=True)
        payload: dict[str, object] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "build_status": "FAIL",
            "system_status": "FAIL",
            "usage_scope": "FEATURE_RESEARCH_ONLY",
            "label_status": "LABELS_NOT_ASSEMBLED",
            "reason_codes": [
                getattr(error, "reason_code", "TPEX_ARCHIVE_FEATURE_BUILD_FAILED")
            ],
        }
        _write_json(audit_path, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
