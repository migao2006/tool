from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IDENTITY_SCHEMA = ROOT / "supabase" / "schema" / "012_security_listing_periods.sql"
IDENTITY_MIGRATION = (
    ROOT / "supabase" / "migrations" / "20260719053000_security_listing_periods.sql"
)
CALENDAR_SCHEMA = ROOT / "supabase" / "schema" / "013_trading_calendar_observations.sql"
CALENDAR_MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260719053500_trading_calendar_observations.sql"
)


def _sql(path: Path) -> str:
    return path.read_text(encoding="utf-8").lower()


def _compact(path: Path) -> str:
    return " ".join(_sql(path).split())


def test_schema_and_versioned_migrations_are_identical() -> None:
    assert _sql(IDENTITY_SCHEMA) == _sql(IDENTITY_MIGRATION)
    assert _sql(CALENDAR_SCHEMA) == _sql(CALENDAR_MIGRATION)


def test_listing_periods_are_lineage_bound_and_fail_closed() -> None:
    sql = _sql(IDENTITY_SCHEMA)

    assert "create table if not exists market_data.security_listing_periods" in sql
    assert "listing_evidence_id bigint generated always as identity primary key" in sql
    assert "listing_period_id text not null" in sql
    assert "identity_resolution_status in ('verified', 'unresolved', 'conflict')" in sql
    assert "source_revision_hash ~ '^[0-9a-f]{64}$'" in sql
    assert "source_payload_hash ~ '^[0-9a-f]{64}$'" in sql
    assert "jsonb_typeof(source_row) = 'object'" in sql
    assert "available_at timestamptz not null" in sql
    assert "available_at_basis = 'official_publication_at'" in sql
    assert "'first_observed_at_retrieval'" in sql
    assert "'versioned_snapshot'" in sql
    assert "asset_type in ('common_stock', 'etf')" in sql
    assert "source_name text" in sql
    assert "isin ~ '^[a-z0-9]{12}$'" in sql
    assert "and isin is not null" in sql
    assert "usage_scope = 'point_in_time_identity'" in sql
    assert "usage_scope = 'identity_research_only'" in sql
    assert "system_status = 'pass'" in sql
    assert "system_status in ('research_only', 'fail')" in sql
    assert "cardinality(reason_codes) = 0" in sql
    assert "cardinality(reason_codes) > 0" in sql
    assert "validate_verified_listing_identity" in sql
    assert "security.asset_type = new.asset_type" in sql
    assert "security.symbol = new.source_symbol" in sql
    assert "security.isin = new.isin" in sql
    assert "security_listing_periods_verified_episode_uidx" in sql


def test_only_verified_identity_periods_receive_overlap_exclusions() -> None:
    sql = _sql(IDENTITY_SCHEMA)

    assert sql.count("exclude using gist") == 2
    assert sql.count("where (identity_resolution_status = 'verified')") == 2
    assert "security_listing_periods_verified_symbol_no_overlap" in sql
    assert "security_listing_periods_verified_security_no_overlap" in sql
    assert "daterange(effective_from, effective_to, '[)') with &&" in sql


def test_calendar_observations_are_versioned_without_overwriting_legacy_table() -> None:
    sql = _sql(CALENDAR_SCHEMA)
    compact_sql = _compact(CALENDAR_SCHEMA)

    assert "create table if not exists market_data.trading_calendar_observations" in sql
    assert "trading_calendar_observations_revision_uidx" in sql
    assert "source_event_id" in sql
    assert "source_revision_hash" in sql
    assert (
        "calendar_verification_status in ( 'verified', 'unresolved', 'conflict' )"
        in compact_sql
    )
    assert "market_basis = 'source_asserted'" in sql
    assert "market_basis = 'scheduling_hint'" not in sql
    assert "usage_scope = 'point_in_time_calendar'" in sql
    assert "usage_scope = 'calendar_research_only'" in sql
    assert "system_status in ('research_only', 'fail')" in sql
    assert "cardinality(reason_codes) = 0" in sql
    assert "cardinality(reason_codes) > 0" in sql
    assert "opens_at is not null" in sql
    assert "closes_at is not null" in sql
    assert "decision_data_cutoff_at is not null" in sql
    assert "closes_at <= decision_data_cutoff_at" in sql
    assert "available_at <= decision_data_cutoff_at" in sql
    assert "trading_calendar_observations_verified_date_uidx" in sql
    assert "where calendar_verification_status = 'verified'" in sql
    assert "alter table market_data.trading_calendar\n" not in sql
    assert "alter table market_data.security_history" not in sql


def test_both_evidence_tables_are_append_only_and_server_only() -> None:
    identity_sql = _sql(IDENTITY_SCHEMA)
    calendar_sql = _sql(CALENDAR_SCHEMA)
    sql = identity_sql + calendar_sql
    compact_sql = _compact(IDENTITY_SCHEMA) + " " + _compact(CALENDAR_SCHEMA)

    assert sql.count("before update or delete") == 2
    assert "security definer" not in sql
    assert "security invoker" in sql
    for table in ("security_listing_periods", "trading_calendar_observations"):
        assert f"alter table market_data.{table} enable row level security" in sql
        assert f"alter table market_data.{table} force row level security" in sql
        assert f"revoke all on market_data.{table}" in sql
        assert (
            f"grant select, insert on market_data.{table} to service_role"
            in compact_sql
        )
        assert f"grant update on market_data.{table}" not in sql
        assert f"grant delete on market_data.{table}" not in sql

    assert "create policy" not in sql
    assert "to anon" not in sql
    assert "to authenticated" not in sql


def test_append_only_correction_contract_preserves_conflicts() -> None:
    identity_sql = _sql(IDENTITY_SCHEMA)
    calendar_sql = _sql(CALENDAR_SCHEMA)

    assert "inserted as conflict" in identity_sql
    assert "never overwrites an existing verified period" in identity_sql
    assert "contradictory evidence is conflict" in calendar_sql
    assert "never overwrites an earlier row" in calendar_sql
