"""Verify one exact-date daily research publish against its target database."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
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

from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402
from src.pipeline.daily_research_publish_contract import (  # noqa: E402
    DAILY_RESEARCH_GATES_PER_PREDICTION,
    MIN_DAILY_RESEARCH_PREDICTIONS,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the report and persisted exact-date prediction run."
    )
    _ = parser.add_argument("--market", choices=("TWSE", "TPEX"), required=True)
    _ = parser.add_argument("--as-of-date", type=date.fromisoformat, required=True)
    _ = parser.add_argument("--target-environment", required=True)
    _ = parser.add_argument("--report", type=Path, required=True)
    _ = parser.add_argument("--output", type=Path)
    return parser


def _read_report(path: Path) -> dict[str, object]:
    try:
        value = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("DAILY_RESEARCH_REPORT_INVALID") from error
    if not isinstance(value, Mapping):
        raise ValueError("DAILY_RESEARCH_REPORT_INVALID")
    return dict(cast(Mapping[str, object], value))


def _positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} is invalid")
    parsed = int(str(value))
    if parsed <= 0:
        raise ValueError(f"{field} is invalid")
    return parsed


def _write(path: Path | None, payload: Mapping[str, object]) -> None:
    rendered = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    market = cast(str, arguments.market)
    as_of_date = cast(date, arguments.as_of_date)
    target = cast(str, arguments.target_environment).strip().lower()
    report_path = cast(Path, arguments.report)
    output = cast(Path | None, arguments.output)
    try:
        report = _read_report(report_path)
        publish = report.get("supabase_publish")
        if (
            report.get("status") != "RESEARCH_ONLY"
            or report.get("market", market) != market
            or report.get("as_of_date") != as_of_date.isoformat()
            or not isinstance(publish, Mapping)
        ):
            raise ValueError("DAILY_RESEARCH_REPORT_SCOPE_MISMATCH")
        publish_record = cast(Mapping[str, object], publish)
        if (
            publish_record.get("status") != "COMPLETED"
            or publish_record.get("target_environment") != target
        ):
            raise ValueError("DAILY_RESEARCH_TARGET_PUBLISH_INCOMPLETE")
        reported_run_id = _positive_integer(
            publish_record.get("prediction_run_id"),
            "prediction_run_id",
        )
        reported_count = _positive_integer(
            publish_record.get("prediction_count"),
            "prediction_count",
        )
        if reported_count < MIN_DAILY_RESEARCH_PREDICTIONS[market]:
            raise ValueError("DAILY_RESEARCH_PREDICTION_COVERAGE_TOO_LOW")

        writer = SupabaseWriter(
            url=os.environ.get("SUPABASE_URL"),
            server_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        )
        runs = writer.select_rows(
            "prediction_runs",
            select=(
                "prediction_run_id,as_of_date,decision_at,horizon,market_scope,"
                "system_validation_status,candidate_count,watch_count,no_trade_count,"
                "hard_fail_count"
            ),
            filters={
                "market_scope": f"eq.{market}",
                "horizon": "eq.5",
                "order": "decision_at.desc,prediction_run_id.desc",
            },
            limit=1,
        )
        if len(runs) != 1:
            raise ValueError("DAILY_RESEARCH_PERSISTED_RUN_MISSING")
        run = runs[0]
        persisted_run_id = _positive_integer(run.get("prediction_run_id"), "run id")
        if (
            persisted_run_id != reported_run_id
            or str(run.get("as_of_date") or "") != as_of_date.isoformat()
            or str(run.get("market_scope") or "") != market
            or int(str(run.get("horizon") or 0)) != 5
            or str(run.get("system_validation_status") or "") != "RESEARCH_ONLY"
        ):
            raise ValueError("DAILY_RESEARCH_PERSISTED_RUN_SCOPE_MISMATCH")
        prediction_rows = writer.select_all_rows(
            "stock_predictions",
            select="stock_prediction_id",
            filters={
                "prediction_run_id": f"eq.{persisted_run_id}",
                "order": "stock_prediction_id.asc",
            },
            page_size=1_000,
            max_rows=5_000,
        )
        prediction_ids = [
            _positive_integer(row.get("stock_prediction_id"), "stock_prediction_id")
            for row in prediction_rows
        ]
        prediction_count = len(prediction_ids)
        gate_count = 0
        for offset in range(0, len(prediction_ids), 100):
            values = ",".join(str(value) for value in prediction_ids[offset : offset + 100])
            gate_count += writer.count_rows(
                "decision_gate_results",
                filters={"stock_prediction_id": f"in.({values})"},
            )
        manifest_count = sum(
            int(str(run.get(field) or 0))
            for field in ("candidate_count", "watch_count", "no_trade_count")
        )
        if (
            prediction_count != reported_count
            or prediction_count != manifest_count
            or gate_count
            != prediction_count * DAILY_RESEARCH_GATES_PER_PREDICTION
        ):
            raise ValueError("DAILY_RESEARCH_PERSISTED_COUNTS_MISMATCH")
        result: dict[str, object] = {
            "schema_version": 1,
            "status": "PASS",
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "target_environment": target,
            "market": market,
            "as_of_date": as_of_date.isoformat(),
            "prediction_run_id": persisted_run_id,
            "prediction_count": prediction_count,
            "decision_gate_count": gate_count,
            "system_status": "RESEARCH_ONLY",
        }
        _write(output, result)
        return 0
    except Exception as error:
        _write(
            output,
            {
                "schema_version": 1,
                "status": "FAIL",
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "target_environment": target,
                "market": market,
                "as_of_date": as_of_date.isoformat(),
                "reason_codes": [
                    str(
                        getattr(
                            error,
                            "reason_code",
                            "DAILY_RESEARCH_PUBLISH_VERIFICATION_FAILED",
                        )
                    )
                ],
                "message": str(error),
            },
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
