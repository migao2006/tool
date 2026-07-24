from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import scripts.verify_daily_research_publish as verifier


class FakeWriter:
    run_overrides: ClassVar[dict[str, object]] = {}
    prediction_overrides: ClassVar[dict[str, object]] = {}

    def __init__(self, *, url: str | None, server_key: str | None) -> None:
        assert url == "https://example.supabase.co"
        assert server_key == "sb_secret_test-value"

    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: dict[str, str],
        limit: int,
    ) -> list[dict[str, object]]:
        del select, filters, limit
        assert table == "prediction_runs"
        return [
            {
                "prediction_run_id": 42,
                "as_of_date": "2026-07-20",
                "horizon": 5,
                "market_scope": "TWSE",
                "system_validation_status": "RESEARCH_ONLY",
                "candidate_count": 0,
                "watch_count": 0,
                "no_trade_count": 0,
                "policy_input_missing_count": 500,
                "policy_validation_failed_count": 0,
                "policy_hard_fail_count": 0,
                "hard_fail_count": 0,
                **self.run_overrides,
            }
        ]

    def select_all_rows(
        self,
        table: str,
        *,
        select: str,
        filters: dict[str, str],
        page_size: int,
        max_rows: int,
    ) -> list[dict[str, object]]:
        del select, filters, page_size, max_rows
        assert table == "stock_predictions"
        return [
            {
                "stock_prediction_id": index + 1,
                "market": "TWSE",
                "decision": None,
                "decision_policy_status": "MISSING_REQUIRED_DATA",
                "data_quality_status": "WARN",
                **self.prediction_overrides,
            }
            for index in range(500)
        ]

    def count_rows(
        self,
        table: str,
        *,
        filters: dict[str, str],
    ) -> int:
        assert table == "decision_gate_results"
        return str(filters["stock_prediction_id"]).count(",") * 8 + 8


def _run(
    tmp_path: Path,
    monkeypatch,
) -> tuple[int, dict[str, object]]:
    FakeWriter.run_overrides = {}
    FakeWriter.prediction_overrides = {}
    monkeypatch.setattr(verifier, "SupabaseWriter", FakeWriter)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "sb_secret_test-value")
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "status": "RESEARCH_ONLY",
                "market": "TWSE",
                "as_of_date": "2026-07-20",
                "supabase_publish": {
                    "status": "COMPLETED",
                    "target_environment": "production",
                    "prediction_run_id": 42,
                    "prediction_count": 500,
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "verification.json"
    status = verifier.main(
        [
            "--market",
            "TWSE",
            "--as-of-date",
            "2026-07-20",
            "--target-environment",
            "production",
            "--report",
            str(report),
            "--output",
            str(output),
        ]
    )
    return status, json.loads(output.read_text(encoding="utf-8"))


def test_verifier_accepts_fail_closed_missing_policy_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    status, payload = _run(tmp_path, monkeypatch)

    assert status == 0
    assert payload["status"] == "PASS"
    assert payload["decision_counts"] == {
        "CANDIDATE": 0,
        "WATCH": 0,
        "NO_TRADE": 0,
        "MISSING_REQUIRED_DATA": 500,
        "VALIDATION_FAILED": 0,
        "HARD_FAIL": 0,
    }


def test_verifier_rejects_missing_status_disguised_as_no_trade(
    tmp_path: Path,
    monkeypatch,
) -> None:
    status, payload = _run(tmp_path, monkeypatch)
    assert status == 0
    assert payload["status"] == "PASS"

    FakeWriter.prediction_overrides = {
        "decision": "NO_TRADE",
    }
    monkeypatch.setattr(verifier, "SupabaseWriter", FakeWriter)
    output = tmp_path / "verification-invalid.json"
    report = tmp_path / "report.json"
    invalid_status = verifier.main(
        [
            "--market",
            "TWSE",
            "--as-of-date",
            "2026-07-20",
            "--target-environment",
            "production",
            "--report",
            str(report),
            "--output",
            str(output),
        ]
    )
    invalid_payload = json.loads(output.read_text(encoding="utf-8"))

    assert invalid_status == 1
    assert invalid_payload["message"] == ("DAILY_RESEARCH_PERSISTED_POLICY_CONTRACT_INVALID")

    FakeWriter.run_overrides = {
        "no_trade_count": 500,
        "policy_input_missing_count": 0,
    }
    FakeWriter.prediction_overrides = {
        "decision": "NO_TRADE",
        "decision_policy_status": "EVALUATED",
        "data_quality_status": "WARN",
    }
    second_output = tmp_path / "verification-warn-action.json"
    second_status = verifier.main(
        [
            "--market",
            "TWSE",
            "--as-of-date",
            "2026-07-20",
            "--target-environment",
            "production",
            "--report",
            str(report),
            "--output",
            str(second_output),
        ]
    )
    second_payload = json.loads(second_output.read_text(encoding="utf-8"))

    assert second_status == 1
    assert second_payload["message"] == ("DAILY_RESEARCH_PERSISTED_POLICY_CONTRACT_INVALID")
