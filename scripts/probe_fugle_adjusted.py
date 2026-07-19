"""Run a bounded read-only Fugle raw-versus-adjusted candle probe."""

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

from src.data.ingestion.fugle_adjusted_probe import (  # noqa: E402
    FugleAdjustedProbe,
)
from src.data.providers.errors import ProviderError  # noqa: E402
from src.data.providers.fugle import FugleClient  # noqa: E402
from src.data.providers.http import JsonHttpClient  # noqa: E402
from src.data.providers.settings import ApiProviderSettings  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare Fugle raw and adjusted candles without storing prices."
    )
    _ = parser.add_argument("--symbol", required=True)
    _ = parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    _ = parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    _ = parser.add_argument("--pacing-seconds", type=float, default=1.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = ApiProviderSettings.from_env()
        summary = FugleAdjustedProbe(
            client=FugleClient(
                api_key=settings.fugle_api_key,
                http=JsonHttpClient(timeout=settings.timeout_seconds),
            )
        ).run(
            symbol=cast(str, args.symbol),
            start_date=cast(date, args.start_date),
            end_date=cast(date, args.end_date),
            pacing_seconds=cast(float, args.pacing_seconds),
        )
        print(
            json.dumps(summary.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        )
        return 0
    except (ProviderError, KeyError, TypeError, ValueError) as error:
        result = {
            "status": "FAIL",
            "reason_code": getattr(
                error, "reason_code", "FUGLE_ADJUSTED_PROBE_INVALID"
            ),
            "message": str(error),
            "writes_performed": 0,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
