"""Fetch one real provider payload into an ignored local raw-data artifact."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
from typing import Sequence

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root

add_project_root()

from src.data.providers.errors import ProviderError  # noqa: E402
from src.data.providers.fetcher import (  # noqa: E402
    ProviderFetchRequest,
    fetch_provider_payload,
)
from src.data.providers.registry import build_provider_registry  # noqa: E402
from src.data.providers.settings import ApiProviderSettings  # noqa: E402


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch one real external API payload.")
    parser.add_argument("provider")
    parser.add_argument("--dataset")
    parser.add_argument("--symbol")
    parser.add_argument("--series-id")
    parser.add_argument("--file-name")
    parser.add_argument("--start-date", type=_date)
    parser.add_argument("--end-date", type=_date)
    parser.add_argument("--as-of-date", type=_date)
    parser.add_argument("--adjusted", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = fetch_provider_payload(
            build_provider_registry(ApiProviderSettings.from_env()),
            ProviderFetchRequest(
                provider=args.provider,
                dataset=args.dataset,
                symbol=args.symbol,
                series_id=args.series_id,
                file_name=args.file_name,
                start_date=args.start_date,
                end_date=args.end_date,
                as_of_date=args.as_of_date,
                adjusted=args.adjusted,
            ),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(payload.to_dict(include_payload=False), ensure_ascii=False, indent=2))
        return 0
    except (ProviderError, ValueError) as error:
        reason_code = getattr(error, "reason_code", "INVALID_FETCH_REQUEST")
        print(json.dumps({"status": "FAIL", "reason_code": reason_code}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
