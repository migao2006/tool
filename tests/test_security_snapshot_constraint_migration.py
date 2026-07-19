from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "supabase/schema/006_security_snapshot_contract.sql"
MIGRATION = ROOT / (
    "supabase/migrations/"
    "20260719090300_allow_late_retrieval_for_current_security_snapshot.sql"
)
ROLLBACK = ROOT / "supabase/snippets/rollback_allow_late_security_snapshot.sql"
VALIDATION = ROOT / "supabase/snippets/validate_allow_late_security_snapshot.sql"


def _compact(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").lower().split())


def test_current_snapshot_accepts_honest_late_retrieval() -> None:
    expected = (
        "snapshot_date <= "
        "(available_at at time zone 'asia/taipei')::date"
    )

    assert expected in _compact(SCHEMA)
    assert expected in _compact(MIGRATION)


def test_current_snapshot_still_rejects_future_source_dates() -> None:
    sql = _compact(MIGRATION)

    assert "effective_from = snapshot_date" in sql
    assert "effective_to = snapshot_date + 1" in sql
    assert "source_revision_hash is not null" in sql
    assert "available_at =" not in sql
    assert "set local lock_timeout = '5s'" in sql
    assert "set local statement_timeout = '60s'" in sql
    assert ") not valid" in sql
    assert "validate constraint security_history_current_snapshot_check_v2" in sql
    assert "delete from" not in sql
    assert "update market_data.security_history" not in sql
    assert "truncate" not in sql
    assert "drop table" not in sql


def test_rollback_fails_closed_when_late_rows_exist() -> None:
    sql = _compact(ROLLBACK)

    assert "rollback_blocked_late_security_snapshot_rows_exist" in sql
    assert "snapshot_date <>" in sql
    assert "raise exception" in sql
    assert "validate constraint security_history_current_snapshot_check_rollback" in sql
    assert (
        "(available_at at time zone 'asia/taipei')::date = snapshot_date"
        in sql
    )


def test_validation_covers_late_and_future_snapshot_paths() -> None:
    sql = _compact(VALIDATION)

    assert "date '2026-07-17'" in sql
    assert "date '2026-07-20'" in sql
    assert "future_security_snapshot_was_not_rejected" in sql
    assert "when check_violation then" in sql
    assert "delete from market_data.security_history" in sql
    assert "delete from market_data.securities" in sql
    assert "delete from market_data.data_sources" in sql
    assert sql.endswith("$$;")
