from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20260718145015_home_data_status.sql"


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_home_data_status_is_a_read_only_public_aggregate() -> None:
    sql = migration_sql()

    assert "create table if not exists public.home_data_status" in sql
    assert "alter table public.home_data_status enable row level security" in sql
    assert "revoke all on table public.home_data_status from public, anon, authenticated" in sql
    assert "grant select on table public.home_data_status to anon, authenticated" in sql
    assert "for select\nto anon, authenticated\nusing (true)" in sql
    assert "grant insert on table public.home_data_status to anon" not in sql
    assert "grant update on table public.home_data_status to authenticated" not in sql


def test_refresh_functions_do_not_expose_privileged_execution() -> None:
    sql = migration_sql()

    assert sql.count("security invoker") == 1
    assert "security definer" not in sql
    assert "revoke all on function market_data.refresh_home_data_status()" in sql
    assert "from public, anon, authenticated" in sql
    assert "grant execute on function market_data.refresh_home_data_status() to service_role" in sql
    assert "pg_advisory_xact_lock" in sql


def test_home_status_preserves_research_only_boundaries() -> None:
    sql = migration_sql()

    assert "model_output_not_available" in sql
    assert "historical_point_in_time_unverified" in sql
    assert "execution_flags_incomplete" in sql
    assert "model_output_incomplete" in sql
    assert "usage_scope = 'production_eligible'" in sql
    assert "where horizon = 5" in sql
    assert "array_remove(" in sql
    assert "latest imported daily-bar trade date; this is not a model decision date" in sql


def test_home_status_does_not_recompute_on_every_source_write() -> None:
    sql = migration_sql()

    assert "create trigger" not in sql
    assert "returns trigger" not in sql
    assert "select market_data.refresh_home_data_status();" in sql


def test_home_status_counts_only_the_latest_five_day_output() -> None:
    sql = migration_sql()

    assert "from market_data.prediction_runs\n        where horizon = 5" in sql
    assert "where prediction_run_id = (" in sql
    assert "output_summary.market_predictions_count = 2" in sql
    assert "output_summary.hard_fail_audit_count = latest_run.hard_fail_count" in sql
