from __future__ import annotations

import json
from pathlib import Path

from src.pipeline.cli import main


def test_cli_reports_research_only_when_real_input_is_missing(capsys) -> None:
    exit_code = main(["train", "--horizon", "5"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["status"] == "RESEARCH_ONLY"
    assert payload["reason_codes"] == ["DATA_SOURCE_NOT_CONFIGURED"]
    assert payload["metrics"] == {}


def test_cli_rejects_unreleased_horizon(capsys) -> None:
    exit_code = main(["backtest", "--horizon", "3"])
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "FAIL"
    assert "only horizon=5" in payload["message"]


def test_cli_writes_machine_readable_report(tmp_path: Path, capsys) -> None:
    report = tmp_path / "run.json"
    exit_code = main(
        [
            "infer",
            "--horizon",
            "5",
            "--as-of-date",
            "2026-07-17",
            "--report",
            str(report),
        ]
    )
    assert exit_code == 2
    assert json.loads(report.read_text(encoding="utf-8"))["mode"] == "infer"
    assert json.loads(capsys.readouterr().out)["status"] == "RESEARCH_ONLY"
