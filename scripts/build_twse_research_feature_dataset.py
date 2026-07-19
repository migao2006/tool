"""Build a feature-only TWSE research dataset from private verified archives."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import cast

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
from src.data.research.twse_archive_feature_builder import (  # noqa: E402
    TwseArchiveFeatureDatasetBuilder,
)
from src.data.research.twse_archive_feature_contracts import (  # noqa: E402
    TWSE_ARCHIVE_SCOPE_FILTERS,
    dataset_snapshot_hash,
)
from src.data.research.twse_archive_feature_parquet import (  # noqa: E402
    TwseArchiveFeatureParquetWriter,
)
from src.data.research.twse_current_identity_repository import (  # noqa: E402
    TwseCurrentIdentityRepository,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Stream fully verified TWSE daily-bar archives into a "
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
    try:
        source = SupabaseWriter(
            url=os.environ.get("SUPABASE_URL"),
            server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        )
        manifests = HistoricalArchiveManifestRepository(source).fetch(
            filters=TWSE_ARCHIVE_SCOPE_FILTERS
        )
        identities = TwseCurrentIdentityRepository(source).fetch()
        dataset_hash = dataset_snapshot_hash(
            source_archive_snapshot_sha256=manifests.snapshot_sha256,
            current_identity_snapshot_sha256=identities.snapshot_sha256,
        )
        writer = TwseArchiveFeatureParquetWriter(
            output_path,
            dataset_snapshot_sha256=dataset_hash,
            source_archive_snapshot_sha256=manifests.snapshot_sha256,
            current_identity_snapshot_sha256=identities.snapshot_sha256,
        )
        audit = TwseArchiveFeatureDatasetBuilder(
            HistoricalParquetReader(R2Client.from_env())
        ).build(
            manifests=manifests,
            identities=identities,
            writer=writer,
        )
        payload = audit.as_json()
        payload["output_file"] = output_path.name
        _write_json(audit_path, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except Exception as error:  # fail closed at the CLI boundary
        payload: dict[str, object] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "build_status": "FAIL",
            "system_status": "FAIL",
            "usage_scope": "FEATURE_RESEARCH_ONLY",
            "label_status": "LABELS_NOT_ASSEMBLED",
            "reason_codes": [
                getattr(error, "reason_code", "TWSE_ARCHIVE_FEATURE_BUILD_FAILED")
            ],
        }
        _write_json(audit_path, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
