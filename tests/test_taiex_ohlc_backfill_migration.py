from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260719103343_taiex_price_index_ohlc_queue.sql"
)
WORKFLOW = ROOT / ".github/workflows/backfill-taiex-monthly-ohlc.yml"
SCRIPT = ROOT / "scripts/backfill_taiex_monthly_ohlc.py"
ROLLBACK = ROOT / "supabase/snippets/rollback_taiex_price_index_ohlc_queue.sql"
VALIDATION = ROOT / "supabase/snippets/validate_taiex_price_index_ohlc_queue.sql"


def test_migration_preserves_exact_archive_scopes_and_adds_taiex() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "provider_code = 'TWSE'" in sql
    assert "source_dataset = 'taiex_price_index_ohlc'" in sql
    assert "schema_version = 'twse_taiex_price_index_ohlc.v1'" in sql
    assert "source_symbol = 'TAIEX'" in sql
    assert "asset_type = 'BENCHMARK'" in sql
    assert "selection_basis = 'FIXED_TAIEX_MONTH_REQUEST'" in sql
    assert "'PRICE_INDEX_NOT_TOTAL_RETURN' = any(reason_codes)" in sql
    assert "point_in_time_status = 'UNVERIFIED'" in sql
    assert "usage_scope = 'RAW_LANDING_ONLY'" in sql
    assert "system_status = 'RESEARCH_ONLY'" in sql
    assert "provider_code = 'FUGLE'" in sql
    assert "source_dataset = 'adjusted_bars'" in sql
    assert "source_symbol ~ '^[1-9][0-9]{3}$'" in sql
    assert "provider_code in ('FINMIND', 'TWSE')" not in sql
    assert "source_dataset in ('benchmark_total_return', 'taiex_price_index_ohlc')" not in sql


def test_month_queue_is_idempotent_completed_month_only_and_service_role_only() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    functions = (
        "seed_taiex_price_index_ohlc_tasks",
        "claim_taiex_price_index_ohlc_task",
        "complete_taiex_price_index_ohlc_task",
        "taiex_price_index_ohlc_backfill_snapshot",
    )

    assert "generate_series(" in sql
    assert "on conflict (" in sql
    assert "do nothing" in sql
    assert "p_end_month >= current_taipei_month" in sql
    assert "completed calendar months only" in sql
    assert "for update of queued skip locked" in sql
    assert "p_lease_seconds not between 60 and 1800" in sql
    assert "security definer" not in sql
    for function in functions:
        assert f"revoke all on function market_data.{function}(" in sql
        assert f"grant execute on function market_data.{function}(" in sql
    assert sql.count("from public, anon, authenticated") >= len(functions)
    assert sql.count("to service_role") >= len(functions)


def test_workflow_is_bounded_paced_retriable_and_does_not_receive_vendor_keys() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "schedule:" in workflow
    assert "TAIEX_PRICE_INDEX_OHLC_BACKFILL_ENABLED" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "--max-tasks" in workflow
    assert "--request-interval-seconds 1.0" in workflow
    assert 'INPUT_START_MONTH: ${{ inputs.start_month' in workflow
    assert '--start-month "$INPUT_START_MONTH"' in workflow
    assert '--max-tasks "$INPUT_MAX_TASKS"' in workflow
    assert '${{ inputs.start_month' not in workflow.split("run: |", 1)[1]
    assert '${{ inputs.end_month' not in workflow.split("run: |", 1)[1]
    assert '${{ inputs.max_tasks' not in workflow.split("run: |", 1)[1]
    assert "upload-artifact@v4" in workflow
    assert "retention-days: 90" in workflow
    assert "FINMIND" not in workflow
    assert "FUGLE" not in workflow
    assert "max_attempts=3" in script
    assert "retry_backoff_seconds=1.0" in script
    assert "PRICE_INDEX_NOT_TOTAL_RETURN" in script
    assert "RAW_LANDING_ONLY" in script


def test_local_validation_and_fail_closed_rollback_are_versioned() -> None:
    validation = VALIDATION.read_text(encoding="utf-8")
    rollback = ROLLBACK.read_text(encoding="utf-8")

    assert "expected three monthly tasks" in validation
    assert "monthly seed is not idempotent" in validation
    assert "current month was incorrectly accepted" in validation
    assert "cross-provider dataset combination was incorrectly accepted" in validation
    assert validation.rstrip().endswith("rollback;")
    assert "rollback blocked: TAIEX OHLC queue or archive records exist" in rollback
    assert "rollback blocked: rollback newer Fugle migration first" in rollback
    assert "historical_archive_scope_check_rollback" in rollback
    assert "historical_backfill_task_identity_check_rollback" in rollback
    assert "provider_code = 'FINMIND'" in rollback
    assert "drop function if exists" in rollback
