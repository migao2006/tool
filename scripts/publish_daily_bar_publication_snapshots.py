"""Publish exact-date TWSE/TPEX current daily-bar snapshots to private R2."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date, datetime, timezone
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

from src.data.ingestion.daily_bar_publication import (  # noqa: E402
    DailyBarPublicationManifestRepository,
    DailyBarPublicationService,
    DailyBarPublicationSourceRepository,
)
from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402
from src.data.object_storage.r2_client import R2Client  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Publish immutable research-only current daily-bar evidence before "
            "daily feature inference."
        )
    )
    _ = parser.add_argument("--as-of-date", type=date.fromisoformat, required=True)
    _ = parser.add_argument(
        "--market",
        action="append",
        choices=("TWSE", "TPEX"),
        dest="markets",
        help="Market to publish. Repeat for both; defaults to TWSE and TPEX.",
    )
    _ = parser.add_argument("--output", type=Path, required=True)
    return parser


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    output = cast(Path, arguments.output)
    as_of_date = cast(date, arguments.as_of_date)
    markets = tuple(dict.fromkeys(cast(list[str] | None, arguments.markets) or []))
    if not markets:
        markets = ("TWSE", "TPEX")
    try:
        writer = SupabaseWriter(
            url=os.environ.get("SUPABASE_URL"),
            server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        )
        source = DailyBarPublicationSourceRepository(writer)
        snapshots = tuple(
            source.fetch(market=market, trading_date=as_of_date) for market in markets
        )
        if {snapshot.trading_date for snapshot in snapshots} != {as_of_date}:
            raise ValueError("DAILY_BAR_PUBLICATION_DATE_MISMATCH")
        service = DailyBarPublicationService(
            store=R2Client.from_env(),
            repository=DailyBarPublicationManifestRepository(writer),
        )
        results = [service.publish(snapshot).to_dict() for snapshot in snapshots]
        payload: dict[str, object] = {
            "status": "RESEARCH_ONLY",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "as_of_date": as_of_date.isoformat(),
            "markets": list(markets),
            "publication_count": len(results),
            "publications": results,
            "reason_codes": [
                "BAR_PUBLICATION_RESEARCH_ONLY",
                "OFFICIAL_PUBLICATION_TIMESTAMP_UNVERIFIED",
            ],
        }
        _write(output, payload)
        return 0
    except Exception as error:  # fail closed at the CLI boundary
        payload = {
            "status": "FAIL",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "as_of_date": as_of_date.isoformat(),
            "markets": list(markets),
            "reason_codes": [
                str(
                    getattr(
                        error,
                        "reason_code",
                        "DAILY_BAR_PUBLICATION_FAILED",
                    )
                )
            ],
            "message": str(error),
        }
        _write(output, payload)
        return 1


if __name__ == "__main__":
    sys.exit(main())
