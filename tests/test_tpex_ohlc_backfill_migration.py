from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260720051630_tpex_price_index_ohlc_queue.sql"
)
ROLLBACK = ROOT / "supabase/snippets/rollback_tpex_price_index_ohlc_queue.sql"
VALIDATION = ROOT / "supabase/snippets/validate_tpex_price_index_ohlc_queue.sql"


def _sql(path: Path) -> str:
    return path.read_text(encoding="utf-8").lower()


def test_archive_allowlist_extends_latest_exact_scopes_without_removing_fugle() -> None:
    sql = _sql(MIGRATION)

    assert "provider_code = 'finmind'" in sql
    assert "provider_code = 'twse'" in sql
    assert "source_dataset = 'taiex_price_index_ohlc'" in sql
    assert "schema_version = 'twse_taiex_price_index_ohlc.v1'" in sql
    assert "provider_code = 'fugle'" in sql
    assert "source_dataset = 'adjusted_bars'" in sql
    assert "source_symbol ~ '^[1-9][0-9]{3}$'" in sql
    assert "provider_code = 'tpex'" in sql
    assert "source_dataset = 'tpex_price_index_ohlc'" in sql
    assert "schema_version = 'tpex_price_index_ohlc.v1'" in sql
    assert "source_symbol = 'tpex_index'" in sql
    assert "scheduled_market = 'tpex'" in sql
    assert "asset_type = 'benchmark'" in sql
    assert "provider_code in ('twse', 'tpex')" not in sql
    assert "provider_code in ('finmind', 'twse', 'tpex')" not in sql
    assert "provider_code = 'tpex'\n            and source_dataset = 'daily_bars'" not in sql


def test_tpex_month_queue_is_completed_month_only_idempotent_and_isolated() -> None:
    sql = _sql(MIGRATION)

    assert "seed_tpex_price_index_ohlc_tasks" in sql
    assert "generate_series(" in sql
    assert "on conflict (" in sql
    assert "do nothing" in sql
    assert "p_end_month >= current_taipei_month" in sql
    assert "tpex ohlc queue accepts completed calendar months only" in sql
    assert "selection_basis = 'fixed_tpex_month_request'" in sql
    assert "security_id is null" in sql
    assert "'point_in_time_unverified' = any(reason_codes)" in sql
    assert "'price_index_not_total_return' = any(reason_codes)" in sql
    assert "usage_scope = 'raw_landing_only'" in sql
    assert "system_status = 'research_only'" in sql

    claim_start = sql.index(
        "create or replace function market_data.claim_tpex_price_index_ohlc_task"
    )
    complete_start = sql.index(
        "create or replace function market_data.complete_tpex_price_index_ohlc_task"
    )
    claim_sql = sql[claim_start:complete_start]
    assert "provider_code = 'tpex'" in claim_sql
    assert "source_dataset = 'tpex_price_index_ohlc'" in claim_sql
    assert "source_symbol = 'tpex_index'" in claim_sql
    assert "market = 'tpex'" in claim_sql
    assert "provider_code = 'twse'" not in claim_sql
    assert "for update of queued skip locked" in claim_sql
    assert "p_lease_seconds not between 60 and 1800" in claim_sql


def test_tpex_rpcs_are_security_invoker_and_service_role_only() -> None:
    sql = _sql(MIGRATION)
    functions = (
        "seed_tpex_price_index_ohlc_tasks",
        "claim_tpex_price_index_ohlc_task",
        "complete_tpex_price_index_ohlc_task",
        "tpex_price_index_ohlc_backfill_snapshot",
    )

    assert "security definer" not in sql
    assert sql.count("security invoker") >= len(functions)
    for function in functions:
        assert f"revoke all on function market_data.{function}(" in sql
        assert f"grant execute on function market_data.{function}(" in sql
    assert sql.count("from public, anon, authenticated") >= len(functions)
    assert sql.count("to service_role") >= len(functions)


def test_validation_covers_queue_isolation_current_month_and_cross_pair() -> None:
    sql = _sql(VALIDATION)

    assert "expected three tpex monthly tasks" in sql
    assert "tpex monthly seed is not idempotent" in sql
    assert "seed_taiex_price_index_ohlc_tasks" in sql
    assert "tpex worker claimed a non-tpex or non-oldest task" in sql
    assert "current tpex month was incorrectly accepted" in sql
    assert "cross-provider tpex dataset was incorrectly accepted" in sql
    assert "tpex rpc privileges are not service-role-only" in sql
    assert sql.rstrip().endswith("rollback;")


def test_rollback_refuses_data_and_restores_finmind_taiex_fugle_scopes() -> None:
    sql = _sql(ROLLBACK)

    assert "rollback blocked: tpex ohlc queue or archive records exist" in sql
    assert "drop function if exists market_data.seed_tpex" in sql
    assert "drop index if exists" in sql
    assert "historical_backfill_tasks_tpex_month_claim_idx" in sql
    assert "provider_code = 'finmind'" in sql
    assert "provider_code = 'twse'" in sql
    assert "source_dataset = 'taiex_price_index_ohlc'" in sql
    assert "provider_code = 'fugle'" in sql
    assert "source_dataset = 'adjusted_bars'" in sql
    assert "source_symbol ~ '^[1-9][0-9]{3}$'" in sql
    assert "provider_code = 'tpex'\n            and source_dataset = 'tpex_price_index_ohlc'" not in sql
    assert "historical_archive_scope_check_rollback" in sql
    assert "historical_backfill_task_identity_check_rollback" in sql
    assert "historical_backfill_task_research_scope_check_rollback" in sql
