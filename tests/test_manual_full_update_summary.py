from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import pytest

import scripts.summarize_manual_full_update as summary_cli
from src.pipeline.manual_full_update_contract import (
    render_manual_full_update_markdown,
    summarize_manual_full_update,
)


TARGET = "2026-07-20"
NOW = datetime(2026, 7, 24, 1, 2, 3, tzinfo=timezone.utc)


def _bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload).encode()


def _import_result(*, source_date: str = TARGET) -> bytes:
    return _bytes(
        {
            "schema_version": 1,
            "status": "PASS",
            "reason_code": "IMPORT_COMPLETED",
            "requested_as_of_date": "2026-07-24",
            "as_of_date": source_date,
            "twse_source_date": source_date,
            "tpex_source_date": source_date,
        }
    )


def _snapshot(
    as_of_date: str,
    *,
    run_id: int,
    prediction_count: int = 500,
) -> dict[str, Any]:
    return {
        "as_of_date": as_of_date,
        "prediction_run_id": run_id,
        "prediction_count": prediction_count,
        "decision_gate_count": prediction_count * 8,
        "system_status": "RESEARCH_ONLY",
    }


def _resolution(
    *,
    target: str = TARGET,
    aligned: str = TARGET,
    required: tuple[str, ...] = (),
    twse: dict[str, Any] | None = None,
    tpex: dict[str, Any] | None = None,
) -> bytes:
    snapshots = {
        "TWSE": twse if twse is not None else _snapshot(TARGET, run_id=10),
        "TPEX": tpex if tpex is not None else _snapshot(TARGET, run_id=20),
    }
    return _bytes(
        {
            "schema_version": 1,
            "status": "PASS",
            "should_run": bool(required),
            "as_of_date": target,
            "aligned_daily_bar_date": aligned,
            "source_age_days": 4,
            "markets": list(required),
            "daily_bar_counts": {"TWSE": 1_079, "TPEX": 889},
            "latest_prediction_dates": {
                market: (
                    snapshot["as_of_date"] if snapshot is not None else None
                )
                for market, snapshot in snapshots.items()
            },
            "validated_production_snapshots": snapshots,
        }
    )


def _verification(
    market: str,
    *,
    as_of_date: str = TARGET,
    prediction_count: int = 500,
    gate_count: int | None = None,
) -> bytes:
    return _bytes(
        {
            "schema_version": 1,
            "status": "PASS",
            "verified_at": "2026-07-24T01:00:00+00:00",
            "target_environment": "production",
            "market": market,
            "as_of_date": as_of_date,
            "prediction_run_id": 100 if market == "TWSE" else 200,
            "prediction_count": prediction_count,
            "decision_gate_count": (
                prediction_count * 8 if gate_count is None else gate_count
            ),
            "system_status": "RESEARCH_ONLY",
        }
    )


def _summarize(**overrides: Any) -> dict[str, object]:
    options: dict[str, Any] = {
        "import_raw": _import_result(),
        "resolution_raw": _resolution(),
        "production_raw": {"TWSE": None, "TPEX": None},
        "actor": "migao2006",
        "repository": "migao2006/tool",
        "branch": "main",
        "sha": "a" * 40,
        "run_id": 123,
        "run_attempt": 1,
        "requested_as_of_date": None,
        "dry_run": False,
        "publish_production": True,
        "production_publish_enabled": True,
        "preflight_result": "success",
        "import_job_result": "success",
        "research_job_result": "success",
        "generated_at": NOW,
    }
    options.update(overrides)
    return summarize_manual_full_update(**options)


def test_one_market_update_composes_exact_final_production_evidence() -> None:
    payload = _summarize(
        resolution_raw=_resolution(
            required=("TWSE",),
            twse=_snapshot("2026-07-17", run_id=9),
        ),
        production_raw={"TWSE": _verification("TWSE"), "TPEX": None},
    )

    assert payload["status"] == "PASS"
    assert payload["outcome"] == "PRODUCTION_UPDATED"
    assert payload["reason_code"] == "PRODUCTION_PUBLISHED_AND_VERIFIED"
    production = payload["production"]
    assert isinstance(production, dict)
    assert production["changed"] is True
    assert production["published_markets"] == ["TWSE"]
    assert production["final_as_of_date"] == TARGET
    assert production["prediction_and_decision_gate_complete"] is True
    markets = production["markets"]
    assert isinstance(markets, dict)
    assert markets["TWSE"]["final_snapshot"]["decision_gate_count"] == 4_000
    assert (
        markets["TWSE"]["final_snapshot"]["evidence_source"]
        == "PRODUCTION_VERIFICATION"
    )
    assert markets["TPEX"]["final_snapshot"]["evidence_source"] == "RESOLUTION"


def test_valid_no_op_is_success_only_from_complete_resolver_evidence() -> None:
    payload = _summarize()

    assert payload["status"] == "PASS"
    assert payload["outcome"] == "NO_CHANGE_REQUIRED"
    assert payload["reason_code"] == "ALREADY_CURRENT"
    production = payload["production"]
    assert isinstance(production, dict)
    assert production["changed"] is False
    assert production["prediction_and_decision_gate_complete"] is True


def test_historical_aligned_supplied_date_is_accepted_end_to_end() -> None:
    payload = _summarize(
        requested_as_of_date=TARGET,
        import_raw=_import_result(source_date="2026-07-23"),
        resolution_raw=_resolution(aligned="2026-07-23"),
    )

    assert payload["status"] == "PASS"
    assert payload["outcome"] == "NO_CHANGE_REQUIRED"


def test_dry_run_allows_newer_source_without_claiming_publication() -> None:
    payload = _summarize(
        import_raw=_import_result(source_date="2026-07-23"),
        resolution_raw=_resolution(
            required=("TWSE", "TPEX"),
            twse=_snapshot("2026-07-17", run_id=9),
            tpex=_snapshot("2026-07-17", run_id=19),
        ),
        dry_run=True,
    )

    assert payload["status"] == "PASS"
    assert payload["outcome"] == "DRY_RUN"
    assert payload["reason_code"] == "DRY_RUN_COMPLETED"
    production = payload["production"]
    assert isinstance(production, dict)
    assert production["changed"] is False
    assert production["published_markets"] == []


def test_staging_only_is_explicit_and_never_claims_production_change() -> None:
    payload = _summarize(
        resolution_raw=_resolution(
            required=("TPEX",),
            tpex=_snapshot("2026-07-17", run_id=19),
        ),
        publish_production=False,
    )

    assert payload["status"] == "PASS"
    assert payload["outcome"] == "STAGING_VERIFIED"
    assert payload["reason_code"] == "PRODUCTION_SKIPPED_BY_INPUT"
    production = payload["production"]
    assert isinstance(production, dict)
    assert production["changed"] is False


@pytest.mark.parametrize(
    ("overrides", "reason_code"),
    [
        (
            {
                "resolution_raw": _resolution(
                    required=("TWSE",),
                    twse=_snapshot("2026-07-17", run_id=9),
                ),
            },
            "PRODUCTION_VERIFICATION_SET_MISMATCH",
        ),
        (
            {
                "resolution_raw": _resolution(
                    required=("TWSE",),
                    twse=_snapshot("2026-07-17", run_id=9),
                ),
                "production_raw": {
                    "TWSE": _verification("TWSE", gate_count=3_999),
                    "TPEX": None,
                },
            },
            "INVALID_PRODUCTION_VERIFICATION_SCOPE",
        ),
        (
            {
                "resolution_raw": _resolution(
                    required=("TWSE",),
                    twse=_snapshot("2026-07-17", run_id=9),
                ),
                "production_publish_enabled": False,
            },
            "PRODUCTION_PUBLISH_GATE_DISABLED",
        ),
        (
            {"research_job_result": "failure"},
            "DAILY_RESEARCH_WORKFLOW_FAILED",
        ),
        (
            {"branch": "feature"},
            "INVALID_MANUAL_TRIGGER_IDENTITY",
        ),
        (
            {"requested_as_of_date": "2026-07-19"},
            "MANUAL_REQUESTED_DATE_NOT_RESOLVED",
        ),
    ],
)
def test_summary_fails_closed_for_invalid_or_incomplete_evidence(
    overrides: dict[str, Any],
    reason_code: str,
) -> None:
    payload = _summarize(**overrides)

    assert payload["status"] == "FAIL"
    assert payload["outcome"] == "FAILED"
    assert payload["reason_code"] == reason_code


def test_import_failure_reason_is_preserved_without_untrusted_message() -> None:
    payload = _summarize(
        import_raw=_bytes(
            {
                "schema_version": 1,
                "status": "FAIL",
                "reason_code": "SOURCE_DATA_STALE",
                "requested_as_of_date": "2026-07-24",
            }
        ),
        import_job_result="failure",
        resolution_raw=None,
    )
    markdown = render_manual_full_update_markdown(payload)

    assert payload["reason_code"] == "SOURCE_DATA_STALE"
    assert "SOURCE_DATA_STALE" in markdown
    assert "message" not in markdown
    assert "token" not in markdown.lower()


def test_markdown_contains_every_required_operator_field() -> None:
    payload = _summarize()
    markdown = render_manual_full_update_markdown(payload)

    for expected in (
        "Trigger:",
        "main",
        "Markets requiring update",
        "Production changed",
        "Final Production as_of_date",
        "Prediction and decision-gate completeness",
        "TWSE",
        "TPEX",
        "Source date",
        "Decision gates",
        "ALREADY_CURRENT",
    ):
        assert expected in markdown


def test_cli_writes_json_and_github_markdown_for_a_no_op(tmp_path: Path) -> None:
    import_path = tmp_path / "import.json"
    resolution_path = tmp_path / "resolution.json"
    output = tmp_path / "summary.json"
    markdown = tmp_path / "step-summary.md"
    import_path.write_bytes(_import_result())
    resolution_path.write_bytes(_resolution())

    status = summary_cli.main(
        [
            "--import-result",
            str(import_path),
            "--resolution-result",
            str(resolution_path),
            "--twse-production-verification",
            str(tmp_path / "missing-twse.json"),
            "--tpex-production-verification",
            str(tmp_path / "missing-tpex.json"),
            "--actor",
            "migao2006",
            "--repository",
            "migao2006/tool",
            "--branch",
            "main",
            "--sha",
            "a" * 40,
            "--run-id",
            "123",
            "--run-attempt",
            "1",
            "--requested-as-of-date",
            "",
            "--dry-run",
            "false",
            "--publish-production",
            "true",
            "--production-publish-enabled",
            "true",
            "--preflight-result",
            "success",
            "--import-job-result",
            "success",
            "--research-job-result",
            "success",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
        ]
    )

    assert status == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["inputs"]["requested_as_of_date"] is None
    assert "ALREADY_CURRENT" in markdown.read_text(encoding="utf-8")
