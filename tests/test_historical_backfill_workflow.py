from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "backfill-historical-daily-bars.yml"
SCRIPT = ROOT / "scripts" / "backfill_historical_daily_bars.py"


def test_backfill_workflow_is_resumable_scheduled_and_capacity_bounded() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'cron: "17 * * * *"' in workflow
    assert "cancel-in-progress: false" in workflow
    assert "timeout-minutes: 30" in workflow
    assert 'FINMIND_QUOTA_RESERVE: "20"' in workflow
    assert 'HISTORICAL_BACKFILL_MAX_RUNTIME_SECONDS: "1200"' in workflow
    assert 'HISTORICAL_BACKFILL_MAX_DATABASE_BYTES: "420000000"' in workflow
    assert "--max-tasks \"$MAX_TASKS\"" in workflow
    assert "FINMIND_TOKEN: ${{ secrets.FINMIND_TOKEN }}" in workflow
    assert "SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}" in workflow


def test_backfill_cli_exposes_only_bounded_campaign_inputs() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    for option in ("--start-date", "--end-date", "--max-tasks", "--output"):
        assert option in script
    assert "--symbols" not in script
    assert "HISTORICAL_BACKFILL_MAX_DATABASE_BYTES" not in script
