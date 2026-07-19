"""Export a versioned TWSE research calendar snapshot from Supabase."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import cast
from uuid import uuid4

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root  # pyright: ignore[reportImplicitRelativeImport]

add_project_root()

from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402
from src.data.research.twse_trading_calendar_snapshot_repository import (  # noqa: E402
    TwseTradingCalendarObservationRepository,
    build_twse_trading_calendar_snapshot,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an immutable-input TWSE research calendar snapshot",
    )
    _ = parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    _ = parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    _ = parser.add_argument("--output", required=True, type=Path)
    _ = parser.add_argument("--audit", required=True, type=Path)
    return parser


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.partial")
    _ = temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _ = temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    output = cast(Path, arguments.output)
    audit = cast(Path, arguments.audit)
    try:
        rows = TwseTradingCalendarObservationRepository(
            SupabaseWriter(
                url=os.environ.get("SUPABASE_URL"),
                server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
            )
        ).fetch(
            start_date=cast(date, arguments.start_date),
            end_date=cast(date, arguments.end_date),
        )
        snapshot = build_twse_trading_calendar_snapshot(rows)
        _write_json(output, snapshot.to_dict())
        payload: dict[str, object] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "build_status": "COMPLETED_RESEARCH_ONLY",
            "system_status": "RESEARCH_ONLY",
            "market": "TWSE",
            "start_date": snapshot.session_dates[0].isoformat(),
            "end_date": snapshot.session_dates[-1].isoformat(),
            "session_count": len(snapshot.sessions),
            "calendar_snapshot_sha256": snapshot.calendar_snapshot_sha256,
            "output_file": output.name,
        }
        _write_json(audit, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as error:  # fail closed at the external I/O boundary
        output.unlink(missing_ok=True)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "build_status": "FAIL",
            "system_status": "FAIL",
            "reason_codes": [
                getattr(error, "reason_code", "TRADING_CALENDAR_SNAPSHOT_BUILD_FAILED")
            ],
        }
        _write_json(audit, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
