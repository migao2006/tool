"""Emit a non-promotional readiness report from R2 and Supabase evidence."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import cast

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root  # pyright: ignore[reportImplicitRelativeImport]

add_project_root()

from src.data.archive.manifest_repository import (  # noqa: E402
    HistoricalArchiveManifestRepository,
)
from src.data.ingestion.contracts import IngestionError  # noqa: E402
from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402
from src.quality.historical_dataset_readiness import (  # noqa: E402
    assess_historical_dataset_readiness,
)
from src.quality.historical_readiness_repository import (  # noqa: E402
    HistoricalReadinessRepository,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit whether historical data can enter the PIT dataset builder."
    )
    _ = parser.add_argument("--archive-audit", type=Path, required=True)
    _ = parser.add_argument("--output", type=Path, required=True)
    return parser


def _read_archive_audit(path: Path) -> Mapping[str, object]:
    try:
        value = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("archive audit report is missing or invalid") from error
    if not isinstance(value, Mapping):
        raise ValueError("archive audit report must be a JSON object")
    return cast(Mapping[str, object], value)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"archive audit contains invalid {field}")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"archive audit contains invalid {field}")
    return value


def _write(path: Path, payload: Mapping[str, object]) -> None:
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
        archive = _read_archive_audit(cast(Path, args.archive_audit))
        integrity_status = archive.get("integrity_status")
        if integrity_status not in {"PASS", "FAIL"}:
            raise ValueError("archive audit contains invalid integrity_status")
        if archive.get("audit_scope") != "FULL":
            raise ValueError("archive audit must cover the full manifest snapshot")
        audited_snapshot_sha256 = _digest(
            archive.get("manifest_snapshot_sha256"),
            "manifest_snapshot_sha256",
        )
        writer = SupabaseWriter(
            url=os.environ.get("SUPABASE_URL"),
            server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        )
        snapshot = HistoricalArchiveManifestRepository(writer).fetch()
        if not snapshot.complete:
            raise ValueError("current manifest snapshot is incomplete")
        if snapshot.snapshot_sha256 != audited_snapshot_sha256:
            raise ValueError(
                "manifest snapshot changed after the archive integrity audit"
            )
        audited_object_count = _integer(archive.get("object_count"), "object_count")
        if snapshot.object_count != audited_object_count:
            raise ValueError("manifest object count changed after the archive audit")
        metrics = HistoricalReadinessRepository(writer).collect(
            archive_integrity_status=cast(str, integrity_status),
            archive_object_count=audited_object_count,
            archive_row_count=_integer(archive.get("row_count"), "row_count"),
            manifest_rows=snapshot.rows,
        )
        result = assess_historical_dataset_readiness(metrics)
        payload: dict[str, object] = {
            "generated_at": generated_at,
            "canonicalization_status": result.canonicalization_status,
            "canonicalization_ready": result.canonicalization_ready,
            "canonicalization_reason_codes": list(
                result.canonicalization_reason_codes
            ),
            "readiness_status": result.readiness_status,
            "dataset_build_ready": result.dataset_build_ready,
            "system_status": result.system_status,
            "reason_codes": list(result.reason_codes),
            "manifest_snapshot_sha256": snapshot.snapshot_sha256,
            "metrics": {
                field: getattr(metrics, field) for field in metrics.__dataclass_fields__
            },
        }
        _write(output, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if result.system_status == "FAIL" else 0
    except (IngestionError, OSError, TypeError, ValueError) as error:
        payload = {
            "generated_at": generated_at,
            "canonicalization_status": "BLOCKED",
            "canonicalization_ready": False,
            "canonicalization_reason_codes": [
                getattr(error, "reason_code", "HISTORICAL_READINESS_AUDIT_FAILED")
            ],
            "readiness_status": "BLOCKED",
            "dataset_build_ready": False,
            "system_status": "FAIL",
            "reason_codes": [
                getattr(error, "reason_code", "HISTORICAL_READINESS_AUDIT_FAILED")
            ],
            "message": str(error),
        }
        _write(output, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
