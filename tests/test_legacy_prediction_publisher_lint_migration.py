from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260720064801_exclude_legacy_prediction_publisher_from_lint.sql"
)
VALIDATION = (
    ROOT
    / "supabase"
    / "snippets"
    / "validate_legacy_prediction_publisher_lint_exclusion.sql"
)
ROLLBACK = (
    ROOT
    / "supabase"
    / "snippets"
    / "rollback_legacy_prediction_publisher_lint_exclusion.sql"
)
MARKET_SCOPE_ROLLBACK = (
    ROOT / "supabase" / "snippets" / "rollback_prediction_runs_market_scope.sql"
)


def read_lower(path: Path) -> str:
    return path.read_text(encoding="utf-8").lower()


def test_migration_only_excludes_unreachable_backup_from_plpgsql_check() -> None:
    sql = read_lower(MIGRATION)

    assert "legacy_prediction_publisher_backup_is_missing" in sql
    assert "legacy_prediction_publisher_backup_must_remain_uncallable" in sql
    assert 'set "plpgsql_check.mode" to \'disabled\'' in sql
    assert "create or replace function" not in sql
    assert "alter table" not in sql
    assert "grant execute" not in sql


def test_validation_preserves_market_identity_and_revoked_privileges() -> None:
    sql = read_lower(VALIDATION)

    assert "plpgsql_check.mode=disabled" in sql
    assert "prediction_runs_market_identity_key" in sql
    assert "unique (market_scope, decision_at, horizon, model_bundle_version)" in sql
    assert "has_function_privilege(" in sql
    assert sql.rstrip().endswith("rollback;")


def test_lint_exclusion_and_full_market_scope_rollback_reset_setting() -> None:
    lint_rollback = read_lower(ROLLBACK)
    market_scope_rollback = read_lower(MARKET_SCOPE_ROLLBACK)
    reset = 'reset "plpgsql_check.mode"'

    assert reset in lint_rollback
    assert reset in market_scope_rollback
    assert market_scope_rollback.index(reset) < market_scope_rollback.index(
        "rename to publish_research_prediction_snapshot"
    )
