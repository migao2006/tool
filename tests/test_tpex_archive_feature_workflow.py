from pathlib import Path

from scripts.check_github_action_pins import reviewed_action_reference


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-tpex-research-feature-dataset.yml"


def test_workflow_is_manual_feature_gated_and_private() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "TPEX_RESEARCH_FEATURE_DATASET_ENABLED == 'true'" in workflow
    assert "scripts.build_tpex_research_feature_dataset" in workflow
    assert "R2_ACCOUNT_ID: ${{ vars.R2_ACCOUNT_ID }}" in workflow
    assert "R2_BUCKET_NAME: ${{ vars.R2_BUCKET_NAME }}" in workflow
    assert "R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}" in workflow
    assert (
        "SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}"
        in workflow
    )
    assert reviewed_action_reference("actions/upload-artifact") in workflow
    assert "tpex-research-features.parquet" in workflow
    assert "tpex-research-features-audit.json" in workflow
    assert "RESEARCH_ONLY" in workflow


def test_workflow_has_no_provider_or_deployment_credentials_and_does_not_write_r2() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    for forbidden in (
        "FINMIND_TOKEN",
        "FUGLE_API_KEY",
        "VERCEL_TOKEN",
        "SENTRY_AUTH_TOKEN",
        "wrangler r2 object put",
        "aws s3 cp",
        "aws s3 sync",
        "delete-object",
    ):
        assert forbidden not in workflow
