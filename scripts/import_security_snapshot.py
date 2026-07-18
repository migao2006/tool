"""Import the current audited security-state snapshot into Supabase."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date, datetime
import json
import sys
from zoneinfo import ZoneInfo

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root  # pyright: ignore[reportImplicitRelativeImport]

add_project_root()

from src.data.ingestion.contracts import IngestionError  # noqa: E402
from src.data.ingestion.security_snapshot_import import (  # noqa: E402
    SecuritySnapshotImporter,
)
from src.data.providers.errors import ProviderError  # noqa: E402
from src.data.providers.settings import ApiProviderSettings  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import the current official Taiwan security-state snapshot."
    )
    parser.add_argument(
        "--snapshot-date",
        type=date.fromisoformat,
        default=datetime.now(ZoneInfo("Asia/Taipei")).date(),
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summary = SecuritySnapshotImporter(
            settings=ApiProviderSettings.from_env()
        ).run(snapshot_date=args.snapshot_date, dry_run=args.dry_run)
        print(
            json.dumps(summary.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        )
        return 0
    except (IngestionError, ProviderError, KeyError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "reason_code": getattr(
                        error, "reason_code", "IMPORT_CONFIGURATION_ERROR"
                    ),
                    "message": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
