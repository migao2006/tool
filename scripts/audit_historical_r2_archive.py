"""Audit every Supabase manifest against its private R2 Parquet object."""

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

from src.data.archive.contracts import HistoricalArchiveReadError  # noqa: E402
from src.data.archive.historical_parquet_reader import HistoricalParquetReader  # noqa: E402
from src.data.archive.manifest_repository import (  # noqa: E402
    HistoricalArchiveManifestRepository,
)
from src.data.ingestion.contracts import IngestionError  # noqa: E402
from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402
from src.data.object_storage.r2_client import R2Client  # noqa: E402
from src.quality.historical_archive_audit import audit_historical_archive  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify Supabase archive manifests against private R2 objects."
    )
    _ = parser.add_argument("--output", type=Path, required=True)
    _ = parser.add_argument(
        "--max-objects",
        type=int,
        help="Optional research sample limit; omit for a complete audit.",
    )
    return parser


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = cast(Path, args.output)
    generated_at = datetime.now(timezone.utc).isoformat()
    try:
        writer = SupabaseWriter(
            url=os.environ.get("SUPABASE_URL"),
            server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        )
        snapshot = HistoricalArchiveManifestRepository(writer).fetch(
            max_objects=cast(int | None, args.max_objects)
        )
        result = audit_historical_archive(
            snapshot.rows,
            reader=HistoricalParquetReader(R2Client.from_env()),
        )
        payload: dict[str, object] = {
            "generated_at": generated_at,
            "integrity_status": result.status,
            "system_status": "RESEARCH_ONLY" if result.passed else "FAIL",
            "audit_scope": "FULL" if snapshot.complete else "LIMITED_SAMPLE",
            "manifest_snapshot_sha256": snapshot.snapshot_sha256,
            "object_count": result.object_count,
            "row_count": result.row_count,
            "byte_count": result.byte_count,
            "reason_codes": list(result.reason_codes),
            "point_in_time_status": "UNVERIFIED",
            "usage_scope": "RAW_LANDING_ONLY",
        }
        _write(output, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result.passed else 1
    except (
        HistoricalArchiveReadError,
        IngestionError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        payload = {
            "generated_at": generated_at,
            "integrity_status": "FAIL",
            "system_status": "FAIL",
            "reason_codes": [
                getattr(error, "reason_code", "HISTORICAL_ARCHIVE_AUDIT_FAILED")
            ],
            "message": str(error),
        }
        _write(output, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
