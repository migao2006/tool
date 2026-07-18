"""Run a bounded, read-only FinMind historical daily-bar probe."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import date
import json
from pathlib import Path
import sys
from typing import cast

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root  # pyright: ignore[reportImplicitRelativeImport]

add_project_root()

from src.data.ingestion.finmind_historical_probe import (  # noqa: E402
    FinMindHistoricalProbe,
)
from src.data.providers.errors import ProviderError  # noqa: E402
from src.data.providers.finmind import FinMindClient  # noqa: E402
from src.data.providers.http import JsonHttpClient  # noqa: E402
from src.data.providers.settings import ApiProviderSettings  # noqa: E402


def _symbols(value: str) -> tuple[str, ...]:
    symbols = tuple(item.strip() for item in value.split(",") if item.strip())
    if not symbols:
        raise argparse.ArgumentTypeError("symbols must be a comma-separated list")
    return symbols


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe explicit FinMind symbols without storing raw data."
    )
    _ = parser.add_argument("--symbols", type=_symbols, required=True)
    _ = parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    _ = parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    _ = parser.add_argument("--pacing-seconds", type=float, default=7.5)
    _ = parser.add_argument("--output", type=Path, required=True)
    return parser


def _write(path: Path, result: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = cast(Path, args.output)
    try:
        settings = ApiProviderSettings.from_env()
        summary = FinMindHistoricalProbe(
            client=FinMindClient(
                token=settings.finmind_token,
                http=JsonHttpClient(timeout=settings.timeout_seconds),
            )
        ).run(
            symbols=cast(tuple[str, ...], args.symbols),
            start_date=cast(date, args.start_date),
            end_date=cast(date, args.end_date),
            pacing_seconds=cast(float, args.pacing_seconds),
        )
        result = summary.to_dict()
        _write(output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (ProviderError, KeyError, TypeError, ValueError) as error:
        result: dict[str, object] = {
            "status": "FAIL",
            "reason_code": getattr(error, "reason_code", "FINMIND_PROBE_INVALID"),
            "message": str(error),
            "writes_performed": 0,
        }
        _write(output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
