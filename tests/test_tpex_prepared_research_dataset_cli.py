from __future__ import annotations

import json
from pathlib import Path

from scripts import build_tpex_prepared_research_dataset as cli


def test_cli_rejects_unreleased_horizon_before_external_access(tmp_path: Path) -> None:
    audit = tmp_path / "audit.json"
    exit_code = cli.main(
        [
            "--feature",
            str(tmp_path / "missing.parquet"),
            "--feature-manifest",
            str(tmp_path / "missing.json"),
            "--output",
            str(tmp_path / "output.parquet"),
            "--audit",
            str(audit),
            "--horizon",
            "3",
        ]
    )

    payload = json.loads(audit.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert payload["reason_codes"] == ["UNSUPPORTED_HORIZON"]
    assert payload["market"] == "TPEX"
    assert payload["system_status"] == "FAIL"


def test_workflow_is_manual_bounded_and_has_no_provider_api_secret() -> None:
    workflow = Path(
        ".github/workflows/build-tpex-prepared-research-dataset.yml"
    ).read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "TPEX_PREPARED_RESEARCH_DATASET_ENABLED" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "timeout-minutes: 120" in workflow
    assert "--horizon 5" in workflow
    assert "FINMIND_TOKEN" not in workflow
    assert "FUGLE_API_KEY" not in workflow
    assert "SUPABASE_SERVICE_ROLE_KEY" in workflow
    assert "R2_SECRET_ACCESS_KEY" in workflow
