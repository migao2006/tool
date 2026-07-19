from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-twse-research-feature-dataset.yml"


def test_workflow_is_manual_feature_gated_and_private() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "TWSE_RESEARCH_FEATURE_DATASET_ENABLED == 'true'" in workflow
    assert "scripts.build_twse_research_feature_dataset" in workflow
    assert "R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}" in workflow
    assert (
        "SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}"
        in workflow
    )
    assert "actions/upload-artifact@v7" in workflow
    assert "twse-research-features.parquet" in workflow
    assert "twse-research-features-audit.json" in workflow
    assert "RESEARCH_ONLY" in workflow
