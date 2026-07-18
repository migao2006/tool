from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "backfill-historical-daily-bars.yml"
WORKER = ROOT / ".github" / "workflows" / "historical-daily-bar-backfill-worker.yml"
SCRIPT = ROOT / "scripts" / "backfill_historical_daily_bars.py"


def test_backfill_workflow_is_resumable_scheduled_and_capacity_bounded() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    worker = WORKER.read_text(encoding="utf-8")
    assert 'cron: "17 * * * *"' in workflow
    assert "cancel-in-progress: false" in workflow
    assert "timeout-minutes: 30" in worker
    assert 'FINMIND_QUOTA_RESERVE: "20"' in worker
    assert 'HISTORICAL_BACKFILL_MAX_RUNTIME_SECONDS: "1200"' in worker
    assert 'HISTORICAL_BACKFILL_MAX_DATABASE_BYTES: "420000000"' in worker
    assert "HISTORICAL_BACKFILL_STORAGE_TARGET: R2" in worker
    assert 'HISTORICAL_BACKFILL_MAX_ARCHIVE_OBJECTS_PER_RUN: "100"' in worker
    assert 'HISTORICAL_BACKFILL_MAX_ARCHIVE_OBJECT_BYTES: "50000000"' in worker
    assert '--max-tasks "$MAX_TASKS"' in worker
    assert "FINMIND_TOKEN: ${{ secrets.finmind_token }}" in worker
    assert (
        "SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.supabase_service_role_key }}" in worker
    )


def test_backfill_workflow_isolates_three_finmind_credentials() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    worker = WORKER.read_text(encoding="utf-8")

    assert "default: 20" in workflow
    assert (
        workflow.count(
            "max_tasks: ${{ fromJSON(github.event.inputs.max_tasks || '20') }}"
        )
        == 3
    )
    assert "r2_account_id:" not in workflow
    assert "r2_bucket_name:" not in workflow
    assert workflow.count("r2_access_key_id: ${{ secrets.R2_ACCESS_KEY_ID }}") == 3
    assert (
        workflow.count("r2_secret_access_key: ${{ secrets.R2_SECRET_ACCESS_KEY }}") == 3
    )
    assert workflow.count("finmind_token:") == 3
    assert workflow.count("finmind_token: ${{ secrets.FINMIND_TOKEN }}") == 1
    assert workflow.count("finmind_token: ${{ secrets.FINMIND_TOKEN_SECONDARY }}") == 1
    assert workflow.count("finmind_token: ${{ secrets.FINMIND_TOKEN_TERTIARY }}") == 1
    assert "FINMIND_TOKEN_SECONDARY" not in worker
    assert "FINMIND_TOKEN_TERTIARY" not in worker
    assert "secrets: inherit" not in workflow
    assert "fail-fast" not in workflow
    for slot in ("primary", "secondary", "tertiary"):
        assert f"credential_slot: {slot}" in workflow
    assert (
        "historical-backfill-${{ inputs.credential_slot }}-${{ github.run_id }}"
        in worker
    )


def test_backfill_worker_requires_complete_r2_configuration() -> None:
    worker = WORKER.read_text(encoding="utf-8")
    credential_check = worker.split("- name: Require backfill credentials", maxsplit=1)[
        1
    ].split("- name: Run quota-aware resumable backfill", maxsplit=1)[0]

    assert "r2_account_id:" not in worker
    assert "r2_bucket_name:" not in worker
    assert "r2_access_key_id:" in worker
    assert "r2_secret_access_key:" in worker
    for name in (
        "FINMIND_TOKEN",
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
    ):
        assert f"          {name}:" in credential_check
        assert f"            {name}\n" in credential_check

    assert "R2_ACCOUNT_ID: ${{ vars.R2_ACCOUNT_ID }}" in worker
    assert "R2_BUCKET_NAME: ${{ vars.R2_BUCKET_NAME }}" in worker
    assert "R2_ACCESS_KEY_ID: ${{ secrets.r2_access_key_id }}" in worker
    assert "R2_SECRET_ACCESS_KEY: ${{ secrets.r2_secret_access_key }}" in worker


def test_backfill_cli_exposes_only_bounded_campaign_inputs() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    for option in ("--start-date", "--end-date", "--max-tasks", "--output"):
        assert option in script
    assert "--symbols" not in script
    assert "HISTORICAL_BACKFILL_MAX_DATABASE_BYTES" not in script
