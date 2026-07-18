"""Import the first auditable ordinary-stock snapshot into Supabase."""

from __future__ import annotations

import argparse
from datetime import date
import json
import sys
from typing import Sequence

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root

add_project_root()

from src.data.ingestion.contracts import IngestionError  # noqa: E402
from src.data.ingestion.daily_import import DailyMarketImporter  # noqa: E402
from src.data.providers.errors import ProviderError  # noqa: E402
from src.data.providers.settings import ApiProviderSettings  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import audited Taiwan market data.")
    parser.add_argument("--as-of-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summary = DailyMarketImporter(settings=ApiProviderSettings.from_env()).run(
            as_of_date=args.as_of_date,
            dry_run=args.dry_run,
        )
        print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (IngestionError, ProviderError, KeyError, ValueError) as error:
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
