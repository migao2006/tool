"""Import the current audited security-state snapshot into Supabase."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date
import json
import sys
from typing import cast

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
    _ = parser.add_argument(
        "--snapshot-date",
        type=date.fromisoformat,
        default=None,
        help=(
            "Profile observation date; omitted resolves the coherent TWSE/TPEX "
            "profile date without claiming a verified trading session"
        ),
    )
    _ = parser.add_argument(
        "--market",
        choices=("TWSE", "TPEX"),
        default=None,
        help=(
            "Import one venue independently. Omit only for the legacy "
            "cross-venue coherent-date operation."
        ),
    )
    _ = parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summary = SecuritySnapshotImporter(settings=ApiProviderSettings.from_env()).run(
            snapshot_date=cast(date | None, args.snapshot_date),
            dry_run=cast(bool, args.dry_run),
            market=cast(str | None, args.market),
        )
        print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (IngestionError, ProviderError, KeyError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "reason_code": getattr(error, "reason_code", "IMPORT_CONFIGURATION_ERROR"),
                    "message": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
