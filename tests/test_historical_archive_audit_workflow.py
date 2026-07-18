from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "audit-historical-r2.yml"


def test_archive_audit_workflow_is_private_complete_and_auditable() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "schedule:" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "scripts.audit_historical_r2_archive" in workflow
    assert "scripts.audit_historical_dataset_readiness" in workflow
    assert "--archive-audit historical-r2-audit.json" in workflow
    assert "--output historical-dataset-readiness.json" in workflow
    assert "--max-objects" not in workflow
    assert "R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}" in workflow
    assert "R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}" in workflow
    assert (
        "SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}"
        in workflow
    )
    assert "actions/upload-artifact@v7" in workflow
    assert "historical-r2-audit.json" in workflow
    assert "historical-dataset-readiness.json" in workflow
    assert workflow.count("if: always()") >= 2
    assert "retention-days: 90" in workflow
