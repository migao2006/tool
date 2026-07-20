from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-tpex-daily-feature-delta.yml"


def test_workflow_runs_only_after_successful_import_or_manual_exact_date() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_run:" in workflow
    assert "- Import market data" in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
    assert "github.event.workflow_run.event == 'schedule'" in workflow
    assert "github.event.workflow_run.event == 'workflow_dispatch'" in workflow
    assert "TPEX_DAILY_FEATURE_DELTA_ENABLED == 'true'" in workflow
    assert "--as-of-date" in workflow
    assert "date.fromisoformat" in workflow


def test_workflow_is_research_only_read_back_verified_and_not_a_deployment() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "scripts.build_tpex_daily_feature_delta" in workflow
    assert "tpex-daily-feature-delta.parquet" in workflow
    assert "tpex-daily-feature-delta-audit.json" in workflow
    assert "tpex-daily-feature-delta-provenance.json" in workflow
    assert "RESEARCH_ONLY" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "retention-days: 90" in workflow
    assert "R2_ACCOUNT_ID: ${{ vars.R2_ACCOUNT_ID }}" in workflow
    assert "R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}" in workflow
    assert (
        "SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}"
        in workflow
    )
    for forbidden in (
        "vercel deploy",
        "vercel promote",
        "supabase db push",
        "wrangler r2 object put",
        "delete-object",
        "FINMIND_TOKEN",
        "FUGLE_API_KEY",
    ):
        assert forbidden not in workflow
