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
    _ = parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Concurrent R2 readers; bounded to 1 through 16.",
    )
    _ = parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Objects verified before atomically persisting a progress checkpoint.",
    )
    return parser


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    _ = temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _ = temporary.replace(path)


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
        workers = cast(int, args.workers)
        batch_size = cast(int, args.batch_size)
        manifest_row_count = sum(cast(int, row["row_count"]) for row in snapshot.rows)
        manifest_byte_count = sum(cast(int, row["byte_size"]) for row in snapshot.rows)
        inspected_object_count = 0
        inspected_row_count = 0
        inspected_byte_count = 0
        last_inspected_archive_id: int | None = None

        def persist_progress(
            inspected: int,
            last_archive_id: int | None,
            inspected_rows: int,
            inspected_bytes: int,
            reason_codes: tuple[str, ...],
        ) -> None:
            nonlocal inspected_object_count, inspected_row_count
            nonlocal inspected_byte_count, last_inspected_archive_id
            inspected_object_count = inspected
            inspected_row_count = inspected_rows
            inspected_byte_count = inspected_bytes
            last_inspected_archive_id = last_archive_id
            _write(
                output,
                {
                    "generated_at": generated_at,
                    "checkpoint_at": datetime.now(timezone.utc).isoformat(),
                    "integrity_status": "IN_PROGRESS",
                    "system_status": "RESEARCH_ONLY",
                    "audit_scope": (
                        "FULL_IN_PROGRESS"
                        if snapshot.complete
                        else "LIMITED_SAMPLE_IN_PROGRESS"
                    ),
                    "manifest_snapshot_sha256": snapshot.snapshot_sha256,
                    "snapshot_high_water_archive_id": (
                        snapshot.high_water_archive_id or 0
                    ),
                    "object_count": snapshot.object_count,
                    "inspected_object_count": inspected,
                    "last_inspected_archive_id": last_archive_id,
                    "planned_row_count": manifest_row_count,
                    "planned_byte_count": manifest_byte_count,
                    "row_count": inspected_rows,
                    "byte_count": inspected_bytes,
                    "reason_codes": list(reason_codes),
                    "audit_workers": workers,
                    "audit_batch_size": batch_size,
                    "point_in_time_status": "UNVERIFIED",
                    "usage_scope": "RAW_LANDING_ONLY",
                },
            )

        result = audit_historical_archive(
            snapshot.rows,
            reader=HistoricalParquetReader(R2Client.from_env()),
            max_workers=workers,
            batch_size=batch_size,
            progress_callback=persist_progress,
        )
        payload: dict[str, object] = {
            "generated_at": generated_at,
            "integrity_status": result.status,
            "system_status": "RESEARCH_ONLY" if result.passed else "FAIL",
            "audit_scope": "FULL" if snapshot.complete else "LIMITED_SAMPLE",
            "manifest_snapshot_sha256": snapshot.snapshot_sha256,
            "snapshot_high_water_archive_id": snapshot.high_water_archive_id or 0,
            "object_count": result.object_count,
            "inspected_object_count": inspected_object_count,
            "last_inspected_archive_id": last_inspected_archive_id,
            "inspected_row_count": inspected_row_count,
            "inspected_byte_count": inspected_byte_count,
            "row_count": result.row_count,
            "byte_count": result.byte_count,
            "reason_codes": list(result.reason_codes),
            "audit_workers": workers,
            "audit_batch_size": batch_size,
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
