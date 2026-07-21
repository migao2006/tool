from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260718170255_historical_backfill_control.sql"
)
FIX_MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260718171030_fix_historical_backfill_claim_priority.sql"
)


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def fix_migration_sql() -> str:
    return FIX_MIGRATION.read_text(encoding="utf-8").lower()


def test_backfill_queue_is_service_role_only_and_rls_protected() -> None:
    sql = migration_sql()

    assert "alter table market_data.historical_backfill_tasks enable row level security" in sql
    assert (
        "revoke all on market_data.historical_backfill_tasks\n"
        "  from public, anon, authenticated"
    ) in sql
    assert (
        "revoke all on sequence market_data.historical_backfill_tasks_task_id_seq\n"
        "  from public, anon, authenticated"
    ) in sql
    assert (
        "grant select, insert, update\n"
        "  on market_data.historical_backfill_tasks to service_role"
    ) in sql
    assert "revoke delete on market_data.historical_backfill_tasks from service_role" in sql
    assert "to anon" not in sql
    assert "to authenticated" not in sql


def test_backfill_rpcs_are_security_invoker_and_not_publicly_executable() -> None:
    sql = migration_sql()

    function_names = (
        "seed_historical_backfill_common_tasks",
        "claim_historical_backfill_tasks",
        "complete_historical_backfill_task",
        "historical_backfill_snapshot",
    )
    assert sql.count("security invoker") == len(function_names)
    assert "security definer" not in sql
    for function_name in function_names:
        assert f"revoke all on function market_data.{function_name}(" in sql
        assert f"grant execute on function market_data.{function_name}(" in sql

    assert sql.count("from public, anon, authenticated") >= len(function_names) + 2
    assert sql.count("to service_role") >= len(function_names) + 2


def test_backfill_priority_is_generated_and_claimed_in_required_order() -> None:
    sql = migration_sql()
    claim_sql = fix_migration_sql()

    assert "when asset_type = 'common_stock' and market = 'twse' then 10" in sql
    assert "when asset_type = 'common_stock' and market = 'tpex' then 20" in sql
    assert "else 30" in sql
    assert "select min(queued.priority) as priority" in claim_sql
    assert "queued.priority = active_priority.priority" in claim_sql
    assert (
        "queued.priority,\n"
        "      queued.requested_start_date,\n"
        "      queued.market,\n"
        "      queued.source_symbol,\n"
        "      queued.task_id"
    ) in claim_sql
    assert "for update of queued skip locked" in claim_sql


def test_claim_hotfix_qualifies_columns_and_preserves_service_role_boundary() -> None:
    sql = fix_migration_sql()

    assert "create or replace function market_data.claim_historical_backfill_tasks(" in sql
    assert "security invoker" in sql
    assert "select queued.task_id" in sql
    assert "select min(queued.priority) as priority" in sql
    assert "queued.priority = active_priority.priority" in sql
    assert "order by\n      queued.priority" in sql
    assert "for update of queued skip locked" in sql
    assert "security definer" not in sql
    assert (
        "revoke all on function market_data.claim_historical_backfill_tasks(\n"
        "  text,\n"
        "  text,\n"
        "  uuid,\n"
        "  integer,\n"
        "  integer\n"
        ") from public, anon, authenticated"
    ) in sql
    assert (
        "grant execute on function market_data.claim_historical_backfill_tasks(\n"
        "  text,\n"
        "  text,\n"
        "  uuid,\n"
        "  integer,\n"
        "  integer\n"
        ") to service_role"
    ) in sql


def test_backfill_lease_is_bounded_reclaimable_and_token_fenced() -> None:
    sql = migration_sql()
    claim_sql = fix_migration_sql()

    assert "if p_limit is null" in claim_sql
    assert "or p_lease_seconds is null" in claim_sql
    assert "or p_limit not between 1 and 100" in claim_sql
    assert "p_lease_seconds not between 60 and 3600" in claim_sql
    assert "update market_data.historical_backfill_tasks as expired" in claim_sql
    assert "expired.status = 'leased'" in claim_sql
    assert "expired.lease_expires_at <= now()" in claim_sql
    assert "expired.attempt_count >= expired.max_attempts" in claim_sql
    assert "queued.attempt_count < queued.max_attempts" in claim_sql
    assert "attempt_count = task.attempt_count + 1" in claim_sql
    assert "lease_token = p_claim_token" in claim_sql
    assert "and task.status = 'leased'" in sql
    assert "and task.lease_token = p_claim_token" in sql
    assert "and task.lease_expires_at > now()" in sql


def test_backfill_completion_rejects_null_or_negative_counters() -> None:
    sql = migration_sql()

    for parameter in (
        "p_success",
        "p_fetched_rows",
        "p_landed_rows",
        "p_quarantined_rows",
        "p_quarantine_issues",
        "p_retry_after_seconds",
    ):
        assert f"or {parameter} is null" in sql
    assert (
        "least(\n"
        "       p_fetched_rows,\n"
        "       p_landed_rows,\n"
        "       p_quarantined_rows,\n"
        "       p_quarantine_issues\n"
        "     ) < 0"
    ) in sql
    assert "successful completion requires latest trade date" in sql


def test_backfill_rows_cannot_be_promoted_beyond_research_landing() -> None:
    sql = migration_sql()

    assert "usage_scope text not null default 'raw_landing_only'" in sql
    assert "system_status text not null default 'research_only'" in sql
    assert "selection_basis = 'current_security_master_scheduling_only'" in sql
    assert "usage_scope = 'raw_landing_only'" in sql
    assert "system_status = 'research_only'" in sql
    assert "'request_universe_not_point_in_time' = any(reason_codes)" in sql
    assert "'historical_vintage_unavailable'" in sql
    assert "'identity_unresolved'" in sql
    assert "system_status = 'pass'" not in sql


def test_backfill_schema_enforces_identity_range_state_and_retry_contracts() -> None:
    sql = migration_sql()

    assert "references market_data.data_sources(source_code) on delete restrict" in sql
    assert "references market_data.securities(security_id) on delete restrict" in sql
    assert "historical_backfill_tasks_security_id_idx" in sql
    assert "market text not null check (market in ('twse', 'tpex'))" in sql
    assert "asset_type text not null check (asset_type in ('common_stock', 'etf'))" in sql
    assert "status in ('pending', 'leased', 'retry', 'succeeded', 'exhausted')" in sql
    assert "requested_start_date <= requested_end_date" in sql
    assert "max_attempts between 1 and 20" in sql
    assert "attempt_count between 0 and max_attempts" in sql
    assert "status in ('pending', 'retry')" in sql
    assert "status in ('succeeded', 'exhausted')" in sql
    assert "status in ('pending', 'leased', 'retry')" in sql
    assert "landing.source_dataset = 'daily_bars'" in sql
    assert "where source_code = 'finmind'" in sql
    assert "min(landing.trade_date) filter" in sql
    assert "coverage.earliest_trade_date <= coverage.range_start" in sql
