from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260720061143_scope_prediction_runs_by_market.sql"
)
VALIDATION = (
    ROOT / "supabase" / "snippets" / "validate_prediction_runs_market_scope.sql"
)
ROLLBACK = ROOT / "supabase" / "snippets" / "rollback_prediction_runs_market_scope.sql"


def read_lower(path: Path) -> str:
    return path.read_text(encoding="utf-8").lower()


def test_migration_proves_legacy_runs_before_twse_backfill() -> None:
    sql = read_lower(MIGRATION)

    assert "add column market_scope text" in sql
    assert (
        "not exists (\n      select 1\n      from market_data.stock_predictions" in sql
    )
    assert "unproven_legacy_prediction_run_market_scope" in sql
    assert "prediction.market is distinct from 'twse'" in sql
    assert "legacy_prediction_child_market_is_not_twse" in sql
    assert "set market_scope = 'twse'" in sql
    assert "alter column market_scope set not null" in sql
    assert "check (market_scope in ('twse', 'tpex'))" in sql


def test_market_identity_and_stale_lookup_are_market_scoped() -> None:
    sql = read_lower(MIGRATION)

    assert "prediction_runs_market_identity_key unique" in sql
    assert (
        "market_scope,\n    decision_at,\n    horizon,\n    model_bundle_version" in sql
    )
    assert "prediction_runs_market_stale_lookup_idx" in sql
    assert "market_scope,\n    horizon,\n    decision_at desc" in sql
    assert "where run.market_scope = v_market_scope" in sql
    assert "and run.horizon = v_horizon" in sql
    assert "stale_research_prediction_snapshot" in sql


def test_publisher_defaults_only_legacy_twse_and_requires_explicit_tpex() -> None:
    sql = read_lower(MIGRATION)

    assert "coalesce(nullif(p_run ->> 'market_scope', ''), 'twse')" in sql
    assert "v_market_scope not in ('twse', 'tpex')" in sql
    assert "item.value ->> 'market' is distinct from v_market_scope" in sql
    assert "|| v_market_scope || ':' || v_horizon::text" in sql
    assert "on conflict (\n    market_scope," in sql
    assert "'market_scope', v_market_scope" in sql


def test_child_market_consistency_and_run_immutability_are_triggered() -> None:
    sql = read_lower(MIGRATION)

    assert "prediction_child_market_scope_mismatch" in sql
    assert "stock_predictions_market_scope_guard" in sql
    assert "market_predictions_market_scope_guard" in sql
    assert "before insert or update of prediction_run_id, market" in sql
    assert "prediction_run_market_scope_is_immutable" in sql
    assert "prediction_runs_market_scope_immutable_guard" in sql


def test_market_scope_functions_are_security_invoker_and_service_role_only() -> None:
    sql = read_lower(MIGRATION)

    assert sql.count("security invoker") >= 3
    assert "security definer" not in sql
    assert (
        "revoke all on function market_data.publish_research_prediction_snapshot("
        in sql
    )
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
    backup_revoke = (
        "publish_research_prediction_snapshot_twse_v1(jsonb, jsonb)\n"
        + "from public, anon, authenticated, service_role"
    )
    assert backup_revoke in sql


def test_validation_covers_market_isolation_upsert_stale_and_privileges() -> None:
    sql = read_lower(VALIDATION)

    assert "coalesce(max(run.decision_at), transaction_timestamp())" in sql
    assert "+ interval '3 days'" in sql
    assert "where run.horizon = 5" in sql
    assert "v_tpex_old_decision_at := v_base_decision_at - interval '1 day'" in sql
    assert "v_tpex_stale_decision_at := v_base_decision_at - interval '2 days'" in sql
    assert "v_training_end_date := v_tpex_stale_as_of_date - 1" in sql
    assert "2026-01-10" not in sql
    assert "2026-01-09" not in sql
    assert "2026-01-08" not in sql
    assert "2025-12-31" not in sql
    assert "legacy twse payload did not default to twse" in sql
    assert "tpex payload without explicit market_scope was accepted" in sql
    assert "older tpex snapshot was accepted" in sql
    assert "market-scoped upsert did not preserve run identity" in sql
    assert "stock child market mismatch was accepted" in sql
    assert "market child scope mismatch was accepted" in sql
    assert "prediction run market_scope mutation was accepted" in sql
    assert "has_function_privilege(" in sql
    assert "procedure.prosecdef" in sql
    assert sql.rstrip().endswith("rollback;")


def test_rollback_refuses_tpex_and_restores_legacy_twse_contract() -> None:
    sql = read_lower(ROLLBACK)

    assert "where market_scope = 'tpex'" in sql
    assert "rollback blocked: tpex prediction runs exist" in sql
    assert "rename to publish_research_prediction_snapshot" in sql
    assert "to service_role" in sql
    assert "prediction_runs_decision_at_horizon_model_bundle_version_key unique" in sql
    assert "drop column market_scope" in sql
