from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260718191828_optimize_historical_backfill_snapshot.sql"
)


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_snapshot_counts_succeeded_task_symbols_without_scanning_landing() -> None:
    sql = migration_sql()

    assert (
        "count(distinct tasks.source_symbol) filter (\n"
        "      where tasks.status = 'succeeded'\n"
        "    )"
    ) in sql
    assert "from market_data.historical_backfill_tasks as tasks" in sql
    assert sql.count("historical_daily_bar_landing") == 1
    assert "pg_total_relation_size('market_data.historical_daily_bar_landing')" in sql


def test_snapshot_preserves_rpc_contract_and_service_role_boundary() -> None:
    sql = migration_sql()

    assert (
        "create or replace function market_data.historical_backfill_snapshot(\n"
        "    p_start_date date,\n"
        "    p_end_date date\n"
        ")"
    ) in sql
    for column in (
        "database_bytes bigint",
        "landing_bytes bigint",
        "landing_symbols bigint",
        "task_count bigint",
        "twse_common_remaining bigint",
        "tpex_common_remaining bigint",
        "etf_task_count bigint",
        "etf_remaining bigint",
        "succeeded bigint",
        "exhausted bigint",
    ):
        assert column in sql

    assert "security invoker" in sql
    assert "security definer" not in sql
    assert (
        "revoke all on function market_data.historical_backfill_snapshot(date, date)\n"
        "from public, anon, authenticated"
    ) in sql
    assert (
        "grant execute on function market_data.historical_backfill_snapshot(date, date)\n"
        "to service_role"
    ) in sql
