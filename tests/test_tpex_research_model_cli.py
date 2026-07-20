from __future__ import annotations

import json
from pathlib import Path

from scripts.run_tpex_research_model import main


def test_tpex_research_cli_rejects_unreleased_horizon(tmp_path: Path) -> None:
    report = tmp_path / "report.json"

    exit_code = main(
        [
            "--input",
            str(tmp_path / "missing.parquet"),
            "--input-audit",
            str(tmp_path / "missing.json"),
            "--report",
            str(report),
            "--horizon",
            "3",
        ]
    )

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert payload["market"] == "TPEX"
    assert payload["reason_codes"] == ["UNSUPPORTED_HORIZON"]


def test_tpex_research_workflow_is_manual_and_local_only() -> None:
    workflow = Path(".github/workflows/run-tpex-oos-research-model.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "TPEX_RESEARCH_MODEL_ENABLED" in workflow
    assert "actions/github-script@v8" in workflow
    assert "getWorkflowRun" in workflow
    assert "build-tpex-prepared-research-dataset.yml" in workflow
    assert 'run.head_branch !== "main"' in workflow
    assert 'run.conclusion !== "success"' in workflow
    assert "compareCommitsWithBasehead" in workflow
    assert "listWorkflowRunArtifacts" in workflow
    assert "TPEX_PREPARED_SOURCE_RUN_SHA" in workflow
    assert "actions/download-artifact@v8" in workflow
    assert "artifact-ids: ${{ steps.prepared-source.outputs.artifact_id }}" in workflow
    assert "digest-mismatch: error" in workflow
    assert "scripts.run_tpex_research_model" in workflow
    assert "SUPABASE_SERVICE_ROLE_KEY" not in workflow
    assert "publish" not in workflow.lower()
