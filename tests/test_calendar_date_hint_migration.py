from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260719065502_allow_research_calendar_date_hints.sql"
)


def _compact_sql() -> str:
    return " ".join(MIGRATION.read_text(encoding="utf-8").lower().split())


def test_calendar_hint_fix_is_forward_only_and_bounded() -> None:
    sql = _compact_sql()

    assert "set local lock_timeout = '5s'" in sql
    assert "set local statement_timeout = '60s'" in sql
    assert sql.count("not valid") == 2
    assert sql.count("validate constraint") == 2
    assert "drop table" not in sql
    assert "truncate" not in sql


def test_calendar_hint_fix_allows_only_complete_or_all_null_sessions() -> None:
    sql = _compact_sql()

    all_null = (
        "opens_at is null and closes_at is null "
        "and decision_data_cutoff_at is null"
    )
    all_present = (
        "opens_at is not null and closes_at is not null "
        "and decision_data_cutoff_at is not null"
    )
    assert sql.count(all_null) >= 3
    assert sql.count(all_present) >= 2
    assert "calendar_verification_status = 'verified'" in sql
    assert "calendar_verification_status in ('unresolved', 'conflict')" in sql
    assert "and available_at <= decision_data_cutoff_at" in sql
    assert "timezone( 'asia/taipei', available_at )::date <= trading_date" in sql
