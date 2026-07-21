"""Resolve the aligned market date that still needs a daily research snapshot."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date, datetime
import json
import os
from pathlib import Path
import sys
from typing import cast
from zoneinfo import ZoneInfo

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root  # pyright: ignore[reportImplicitRelativeImport]

add_project_root()

from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402


TAIPEI = ZoneInfo("Asia/Taipei")
MIN_ROWS = {"TWSE": 500, "TPEX": 500}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve one aligned production daily-bar date for daily inference."
    )
    _ = parser.add_argument("--as-of-date", type=date.fromisoformat)
    _ = parser.add_argument("--max-age-days", type=int, default=7)
    _ = parser.add_argument("--output", type=Path)
    _ = parser.add_argument("--github-output", type=Path)
    return parser


def _date(value: object, field_name: str) -> date:
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError as error:
        raise ValueError(f"{field_name} is not a valid date") from error


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} is not an integer")
    parsed = int(str(value))
    if parsed < 0:
        raise ValueError(f"{field_name} is negative")
    return parsed


def _latest_prediction_date(writer: SupabaseWriter, market: str) -> date | None:
    rows = writer.select_rows(
        "prediction_runs",
        select="prediction_run_id,as_of_date,decision_at",
        filters={
            "market_scope": f"eq.{market}",
            "horizon": "eq.5",
            "order": "decision_at.desc,prediction_run_id.desc",
        },
        limit=1,
    )
    return _date(rows[0].get("as_of_date"), "prediction as_of_date") if rows else None


def _reason_code(error: Exception) -> str:
    explicit = str(getattr(error, "reason_code", "")).strip()
    if explicit:
        return explicit
    message = str(error).strip()
    if message and all(
        character.isupper() or character.isdigit() or character == "_" for character in message
    ):
        return message
    return "DAILY_RESEARCH_DATE_RESOLUTION_FAILED"


def _write_github_outputs(path: Path, payload: dict[str, object]) -> None:
    lines = [
        f"should_run={'true' if payload['should_run'] else 'false'}",
        f"as_of_date={payload['as_of_date']}",
        "markets=" + json.dumps(payload["markets"], separators=(",", ":")),
    ]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    max_age_days = cast(int, arguments.max_age_days)
    if not 0 <= max_age_days <= 31:
        raise SystemExit("max-age-days must be between 0 and 31")
    try:
        public = SupabaseWriter(
            url=os.environ.get("SUPABASE_URL"),
            server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
            schema="public",
        )
        status_rows = public.select_rows(
            "home_data_status",
            select=(
                "status_key,as_of_date,daily_bars_latest_date,"
                "twse_daily_bars_latest_count,tpex_daily_bars_latest_count,updated_at"
            ),
            filters={"status_key": "eq.latest"},
            limit=2,
        )
        if len(status_rows) != 1:
            raise ValueError("HOME_DATA_STATUS_UNAVAILABLE")
        status = status_rows[0]
        aligned_date = _date(
            status.get("daily_bars_latest_date") or status.get("as_of_date"),
            "daily_bars_latest_date",
        )
        requested = cast(date | None, arguments.as_of_date)
        target = requested or aligned_date
        if target > aligned_date:
            raise ValueError("REQUESTED_DAILY_BAR_DATE_NOT_AVAILABLE")
        today = datetime.now(TAIPEI).date()
        age_days = (today - target).days
        if age_days < 0:
            raise ValueError("DAILY_RESEARCH_SOURCE_DATE_FROM_FUTURE")
        counts = {
            "TWSE": _integer(
                status.get("twse_daily_bars_latest_count"),
                "twse_daily_bars_latest_count",
            ),
            "TPEX": _integer(
                status.get("tpex_daily_bars_latest_count"),
                "tpex_daily_bars_latest_count",
            ),
        }
        market_data = SupabaseWriter(
            url=os.environ.get("SUPABASE_URL"),
            server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        )
        latest_predictions = {
            market: _latest_prediction_date(market_data, market) for market in ("TWSE", "TPEX")
        }
        missing = [
            market
            for market in ("TWSE", "TPEX")
            if latest_predictions[market] is None or cast(date, latest_predictions[market]) < target
        ]
        # A long exchange closure must be a clean no-op when both markets already
        # have the latest aligned snapshot. Apply freshness and coverage gates only
        # when this run would actually publish a missing market.
        if missing and age_days > max_age_days:
            raise ValueError("DAILY_RESEARCH_SOURCE_DATE_OUTSIDE_ALLOWED_AGE")
        if target == aligned_date and any(counts[market] < MIN_ROWS[market] for market in missing):
            raise ValueError("DAILY_RESEARCH_SOURCE_COVERAGE_TOO_LOW")
        payload: dict[str, object] = {
            "status": "PASS",
            "should_run": bool(missing),
            "as_of_date": target.isoformat(),
            "aligned_daily_bar_date": aligned_date.isoformat(),
            "source_age_days": age_days,
            "markets": missing,
            "daily_bar_counts": counts,
            "latest_prediction_dates": {
                market: (value.isoformat() if value is not None else None)
                for market, value in latest_predictions.items()
            },
        }
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        output = cast(Path | None, arguments.output)
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            _ = output.write_text(rendered + "\n", encoding="utf-8")
        github_output = cast(Path | None, arguments.github_output)
        if github_output is not None:
            _write_github_outputs(github_output, payload)
        print(rendered)
        return 0
    except Exception as error:
        payload = {
            "status": "FAIL",
            "should_run": False,
            "as_of_date": None,
            "markets": [],
            "reason_codes": [_reason_code(error)],
            "message": str(error),
        }
        output = cast(Path | None, arguments.output)
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            _ = output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 1


if __name__ == "__main__":
    sys.exit(main())
