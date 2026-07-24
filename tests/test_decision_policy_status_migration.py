from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20260724044115_decision_policy_status_semantics.sql"


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_separates_policy_actions_from_evaluation_status() -> None:
    sql = migration_sql()

    assert "add column decision_policy_status text" in sql
    assert "alter column decision drop not null" in sql
    for status in (
        "EVALUATED",
        "MISSING_REQUIRED_DATA",
        "VALIDATION_FAILED",
        "HARD_FAIL",
    ):
        assert status in sql
    assert "decision_policy_status = 'EVALUATED'" in sql
    assert "decision is not null" in sql
    assert "decision_policy_status <> 'EVALUATED'" in sql
    assert "decision is null" in sql
    assert "data_quality_status in ('PASS', 'WARN', 'HARD_FAIL')" in sql


def test_migration_backfills_legacy_research_rows_fail_closed() -> None:
    sql = migration_sql()

    assert "run.system_validation_status in ('RESEARCH_ONLY', 'FAIL')" in sql
    assert "REQUIRED_DECISION_POLICY_DATA_MISSING" in sql
    assert "RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY" in sql
    assert "RESEARCH_DATA_QUALITY_WARN" in sql
    assert "from market_data.data_quality_audits as audit" in sql
    assert "and audit.hard_fail" in sql
    assert "and not audit.hard_fail" in sql
    assert "set\n  decision = null" in sql
    assert "where decision_policy_status <> 'EVALUATED'" in sql
    assert "decision_policy_status <> 'EVALUATED'\n        or data_quality_status = 'PASS'" in sql
    assert "DECISION_POLICY_VALIDATION_FAILED" in sql


def test_migration_recomputes_and_exposes_all_mutually_exclusive_counts() -> None:
    sql = migration_sql()

    for counter in (
        "candidate_count",
        "watch_count",
        "no_trade_count",
        "policy_input_missing_count",
        "policy_validation_failed_count",
        "policy_hard_fail_count",
        "hard_fail_count",
    ):
        assert counter in sql
    assert "RESEARCH_DECISION_POLICY_COUNTS_DO_NOT_MATCH_ROWS" in sql
    assert "RESEARCH_DECISION_POLICY_STATUS_COVERAGE_INCOMPLETE" in sql
    assert "get_prediction_snapshot_rows_policy_v1" in sql
    assert "'decision_policy_status'," in sql


def test_read_rpc_remains_security_invoker() -> None:
    sql = migration_sql()
    active_read_rpc = sql.split(
        "create function market_data.get_prediction_snapshot_rows(",
        maxsplit=1,
    )[1].split("end\n$function$;", maxsplit=1)[0]

    assert "security invoker" in active_read_rpc
    assert "security definer" not in active_read_rpc
    assert "grant execute on function market_data.get_prediction_snapshot_rows_policy_v1(" in sql


def test_legacy_publisher_rejects_unknown_quality_instead_of_promoting_it() -> None:
    sql = migration_sql()

    assert "INVALID_LEGACY_RESEARCH_DECISION_POLICY_CONTRACT" in sql
    assert "'FAIL'," in sql
    assert "'HARD_FAIL'" in sql


def test_migration_keeps_the_publisher_atomic_and_service_role_only() -> None:
    sql = migration_sql()

    assert sql.startswith("begin;")
    assert "\ncommit;\n" in sql
    assert "security definer" in sql
    assert "alpha_lens.decision_policy_bridge" in sql
    assert "current_user = pg_get_userbyid" in sql
    assert "RESEARCH_DECISION_POLICY_ATOMIC_ROW_COUNT_MISMATCH" in sql
    assert (
        "revoke all on function\nmarket_data.publish_research_prediction_snapshot_policy_v1" in sql
    )
    assert "grant execute on function market_data.publish_research_prediction_snapshot(" in sql
    assert ") to service_role;" in sql


def test_home_summary_uses_the_complete_policy_manifest_and_one_market() -> None:
    sql = migration_sql()

    assert "+ latest_run.policy_input_missing_count" in sql
    assert "+ latest_run.policy_validation_failed_count" in sql
    assert "+ latest_run.policy_hard_fail_count" in sql
    assert "count(prediction.stock_prediction_id)::integer as stock_count" in sql
    assert "and output_summary.stock_count > 0" in sql
    assert "output_summary.market_count = 1" in sql
    assert "market = latest_run.market_scope" in sql
