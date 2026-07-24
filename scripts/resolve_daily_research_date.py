"""Resolve the aligned market date that still needs a daily research snapshot."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
import json
import os
from pathlib import Path
import sys
import time
from typing import cast
from zoneinfo import ZoneInfo

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root  # pyright: ignore[reportImplicitRelativeImport]

add_project_root()

from src.data.ingestion.contracts import IngestionError  # noqa: E402
from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402
from src.pipeline.daily_research_publish_contract import (  # noqa: E402
    DAILY_RESEARCH_GATES_PER_PREDICTION,
)


TAIPEI = ZoneInfo("Asia/Taipei")
MIN_ROWS = {"TWSE": 500, "TPEX": 500}
MAX_PREDICTIONS = 5_000
RESOLUTION_TIMEOUT_SECONDS = 60.0
RESOLUTION_RETRY_DELAYS_SECONDS = (1.0, 2.0)
DECISION_COUNT_FIELDS = {
    "CANDIDATE": "candidate_count",
    "WATCH": "watch_count",
    "NO_TRADE": "no_trade_count",
}
POLICY_STATUS_COUNT_FIELDS = {
    "MISSING_REQUIRED_DATA": "policy_input_missing_count",
    "VALIDATION_FAILED": "policy_validation_failed_count",
    "HARD_FAIL": "policy_hard_fail_count",
}
DATA_QUALITY_STATUSES = {"PASS", "WARN", "HARD_FAIL"}


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


@dataclass(frozen=True)
class ValidatedProductionSnapshot:
    as_of_date: date
    prediction_run_id: int
    prediction_count: int
    decision_gate_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "as_of_date": self.as_of_date.isoformat(),
            "prediction_run_id": self.prediction_run_id,
            "prediction_count": self.prediction_count,
            "decision_gate_count": self.decision_gate_count,
            "system_status": "RESEARCH_ONLY",
        }


def _latest_prediction_snapshot(
    writer: SupabaseWriter,
    market: str,
) -> ValidatedProductionSnapshot | None:
    rows = writer.select_rows(
        "prediction_runs",
        select=(
            "prediction_run_id,as_of_date,decision_at,horizon,market_scope,"
            "system_validation_status,candidate_count,watch_count,no_trade_count,"
            "policy_input_missing_count,policy_validation_failed_count,"
            "policy_hard_fail_count,hard_fail_count"
        ),
        filters={
            "market_scope": f"eq.{market}",
            "horizon": "eq.5",
            "order": "decision_at.desc,prediction_run_id.desc",
        },
        limit=1,
    )
    if not rows:
        return None
    run = rows[0]
    try:
        run_id = _integer(run.get("prediction_run_id"), "prediction_run_id")
        as_of_date = _date(run.get("as_of_date"), "prediction as_of_date")
        counts = {
            field: _integer(run.get(field), field)
            for field in (
                "candidate_count",
                "watch_count",
                "no_trade_count",
                "policy_input_missing_count",
                "policy_validation_failed_count",
                "policy_hard_fail_count",
                "hard_fail_count",
            )
        }
    except (TypeError, ValueError):
        return None
    if (
        run_id < 1
        or run.get("market_scope") != market
        or run.get("horizon") != 5
        or run.get("system_validation_status") != "RESEARCH_ONLY"
        or counts["candidate_count"] != 0
        or counts["hard_fail_count"] < counts["policy_hard_fail_count"]
    ):
        return None
    predictions = writer.select_all_rows(
        "stock_predictions",
        select=("stock_prediction_id,market,decision,decision_policy_status,data_quality_status"),
        filters={
            "prediction_run_id": f"eq.{run_id}",
            "order": "stock_prediction_id.asc",
        },
        page_size=1_000,
        max_rows=MAX_PREDICTIONS,
    )
    try:
        prediction_ids = [
            _integer(row.get("stock_prediction_id"), "stock_prediction_id") for row in predictions
        ]
    except (TypeError, ValueError):
        return None
    prediction_count = len(prediction_ids)
    actual_counts = {field: 0 for field in counts if field != "hard_fail_count"}
    rows_valid = True
    for row in predictions:
        status = row.get("decision_policy_status")
        decision = row.get("decision")
        quality = row.get("data_quality_status")
        if (
            row.get("market") != market
            or status
            not in {
                "EVALUATED",
                "MISSING_REQUIRED_DATA",
                "VALIDATION_FAILED",
                "HARD_FAIL",
            }
            or quality not in DATA_QUALITY_STATUSES
            or (status == "EVALUATED") != (decision in DECISION_COUNT_FIELDS)
            or (status == "EVALUATED" and quality != "PASS")
            or (status == "HARD_FAIL") != (quality == "HARD_FAIL")
        ):
            rows_valid = False
            break
        if status == "EVALUATED":
            actual_counts[DECISION_COUNT_FIELDS[cast(str, decision)]] += 1
        else:
            actual_counts[POLICY_STATUS_COUNT_FIELDS[cast(str, status)]] += 1
    if (
        prediction_count < MIN_ROWS[market]
        or prediction_count != sum(actual_counts.values())
        or len(set(prediction_ids)) != prediction_count
        or not rows_valid
        or any(actual_counts[field] != counts[field] for field in actual_counts)
    ):
        return None
    gate_count = 0
    for offset in range(0, prediction_count, 100):
        values = ",".join(str(value) for value in prediction_ids[offset : offset + 100])
        gate_count += writer.count_rows(
            "decision_gate_results",
            filters={"stock_prediction_id": f"in.({values})"},
        )
    if gate_count != prediction_count * DAILY_RESEARCH_GATES_PER_PREDICTION:
        return None
    return ValidatedProductionSnapshot(
        as_of_date=as_of_date,
        prediction_run_id=run_id,
        prediction_count=prediction_count,
        decision_gate_count=gate_count,
    )


def _latest_prediction_date(writer: SupabaseWriter, market: str) -> date | None:
    """Compatibility helper for callers that only need the validated date."""

    snapshot = _latest_prediction_snapshot(writer, market)
    return snapshot.as_of_date if snapshot is not None else None


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


def _resolution_writer(*, schema: str = "market_data") -> SupabaseWriter:
    return SupabaseWriter(
        url=os.environ.get("SUPABASE_URL"),
        server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        schema=schema,
        timeout=RESOLUTION_TIMEOUT_SECONDS,
    )


def _resolve_once(
    *,
    requested: date | None,
    max_age_days: int,
) -> dict[str, object]:
    public = _resolution_writer(schema="public")
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
    market_data = _resolution_writer()
    latest_snapshots = {
        market: _latest_prediction_snapshot(market_data, market) for market in ("TWSE", "TPEX")
    }
    missing = [
        market
        for market in ("TWSE", "TPEX")
        if latest_snapshots[market] is None
        or cast(
            ValidatedProductionSnapshot,
            latest_snapshots[market],
        ).as_of_date
        < target
    ]
    # A long exchange closure must be a clean no-op when both markets already
    # have the latest aligned snapshot. Apply freshness and coverage gates only
    # when this run would actually publish a missing market.
    if missing and age_days > max_age_days:
        raise ValueError("DAILY_RESEARCH_SOURCE_DATE_OUTSIDE_ALLOWED_AGE")
    if target == aligned_date and any(counts[market] < MIN_ROWS[market] for market in missing):
        raise ValueError("DAILY_RESEARCH_SOURCE_COVERAGE_TOO_LOW")
    return {
        "schema_version": 1,
        "status": "PASS",
        "should_run": bool(missing),
        "as_of_date": target.isoformat(),
        "aligned_daily_bar_date": aligned_date.isoformat(),
        "source_age_days": age_days,
        "markets": missing,
        "daily_bar_counts": counts,
        "latest_prediction_dates": {
            market: (snapshot.as_of_date.isoformat() if snapshot is not None else None)
            for market, snapshot in latest_snapshots.items()
        },
        "validated_production_snapshots": {
            market: (snapshot.to_dict() if snapshot is not None else None)
            for market, snapshot in latest_snapshots.items()
        },
    }


def _resolve_with_connection_retry(
    resolve_once: Callable[[], dict[str, object]],
    *,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    for attempt in range(len(RESOLUTION_RETRY_DELAYS_SECONDS) + 1):
        try:
            return resolve_once()
        except IngestionError as error:
            if error.reason_code != "SUPABASE_CONNECTION_ERROR" or attempt == len(
                RESOLUTION_RETRY_DELAYS_SECONDS
            ):
                raise
            delay = RESOLUTION_RETRY_DELAYS_SECONDS[attempt]
            print(
                "Retrying Production snapshot resolution after "
                f"{error.reason_code} (attempt {attempt + 2}/3)",
                file=sys.stderr,
            )
            sleeper(delay)
    raise AssertionError("unreachable daily research resolution retry state")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    max_age_days = cast(int, arguments.max_age_days)
    if not 0 <= max_age_days <= 31:
        raise SystemExit("max-age-days must be between 0 and 31")
    try:
        requested = cast(date | None, arguments.as_of_date)
        payload = _resolve_with_connection_retry(
            lambda: _resolve_once(
                requested=requested,
                max_age_days=max_age_days,
            )
        )
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
            "schema_version": 1,
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
