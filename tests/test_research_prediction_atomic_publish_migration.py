from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260719152201_publish_research_snapshot_atomically.sql"
)


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_atomic_publish_rpc_is_service_role_only_and_security_invoker() -> None:
    sql = migration_sql()
    assert "security invoker" in sql
    assert "security definer" not in sql
    assert (
        "revoke all on function market_data.publish_research_prediction_snapshot("
        in sql
    )
    assert "from public, anon, authenticated" in sql
    assert (
        "grant execute on function market_data.publish_research_prediction_snapshot("
        in sql
    )
    assert "to service_role" in sql
    assert "to anon" not in sql
    assert "to authenticated" not in sql


def test_atomic_publish_serializes_and_rejects_older_decisions() -> None:
    sql = migration_sql()

    assert "pg_advisory_xact_lock" in sql
    assert "select max(prediction_runs.decision_at)" in sql
    assert "v_decision_at < v_latest_decision_at" in sql
    assert "stale_research_prediction_snapshot" in sql
    assert "for update" in sql


def test_atomic_publish_upserts_one_run_and_its_complete_stock_rows() -> None:
    sql = migration_sql()

    assert "insert into market_data.prediction_runs" in sql
    assert "on conflict (decision_at, horizon, model_bundle_version) do update" in sql
    assert "insert into market_data.stock_predictions" in sql
    assert "on conflict (prediction_run_id, security_id) do update" in sql
    assert "delete from market_data.stock_predictions as existing" in sql
    assert "select count(*)::integer" in sql
    assert "research_prediction_atomic_row_count_mismatch" in sql
    assert "jsonb_build_object(" in sql
    assert "'prediction_run_id', v_prediction_run_id" in sql
    assert "'prediction_count', v_actual_count" in sql


def test_atomic_publish_preserves_research_scope_and_snapshot_provenance() -> None:
    sql = migration_sql()

    for scope in (
        "out_of_sample_test",
        "daily_research_inference",
        "retrospective_research_inference",
    ):
        assert f"'{scope}'" in sql
    assert "v_source_dates ->> 'prediction_scope'" in sql
    assert "v_source_dates ->> 'feature_snapshot'" in sql
    assert "v_source_dates ->> 'snapshot_sha256'" in sql
    assert "research_only" in sql
    assert "candidate_count" in sql
    assert "no_trade_count" in sql
