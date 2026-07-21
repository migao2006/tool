from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260720170000_prediction_snapshot_rate_limit.sql"
)
VALIDATION = ROOT / "supabase/snippets/validate_prediction_snapshot_rate_limit.sql"
ROLLBACK = ROOT / "supabase/snippets/rollback_prediction_snapshot_rate_limit.sql"


def compact(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_rate_limit_store_keeps_only_opaque_keys_and_atomic_counters() -> None:
    sql = compact(MIGRATION)

    assert "create table market_data.prediction_snapshot_rate_limits" in sql
    assert "rate_limit_key_sha256 text primary key" in sql
    assert "check (rate_limit_key_sha256 ~ '^[0-9a-f]{64}$')" in sql
    assert "on conflict (rate_limit_key_sha256) do update" in sql
    assert "least(current_window.request_count + 1, p_max_requests + 1)" in sql
    assert "raw client addresses must never be persisted" in sql
    assert "client_ip" not in sql
    assert "ip_address" not in sql


def test_rate_limit_contract_is_bounded_and_service_role_only() -> None:
    sql = compact(MIGRATION)

    assert "p_window_seconds > 3600" in sql
    assert "p_max_requests > 10000" in sql
    assert "security invoker" in sql
    assert "security definer" not in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql


def test_validation_covers_allow_deny_privileges_and_invoker_mode() -> None:
    sql = compact(VALIDATION)

    assert "first_rate_limit_decision_invalid" in sql
    assert "second_rate_limit_decision_invalid" in sql
    assert "third_rate_limit_decision_invalid" in sql
    assert "rate_limit_function_exposed_to_browser_roles" in sql
    assert "rate_limit_function_missing_service_role_grant" in sql
    assert "rate_limit_function_must_be_security_invoker" in sql
    assert sql.endswith("rollback;")


def test_rollback_removes_only_the_operational_rate_limit_objects() -> None:
    sql = compact(ROLLBACK)

    assert "drop function market_data.consume_prediction_snapshot_rate_limit" in sql
    assert "drop table market_data.prediction_snapshot_rate_limits" in sql
    for forbidden in (
        "drop table market_data.prediction_runs",
        "drop table market_data.stock_predictions",
        "truncate",
    ):
        assert forbidden not in sql
