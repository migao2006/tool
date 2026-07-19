from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (
    ROOT / "supabase" / "schema" / "015_historical_company_action_evidence.sql"
)
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260719055000_historical_company_action_evidence.sql"
)


def _sql(path: Path) -> str:
    return path.read_text(encoding="utf-8").lower()


def _compact(path: Path) -> str:
    return " ".join(_sql(path).split())


def test_schema_reference_matches_versioned_migration() -> None:
    assert _sql(SCHEMA) == _sql(MIGRATION)


def test_event_and_complete_coverage_contracts_are_separate() -> None:
    sql = _sql(SCHEMA)

    assert (
        "create table if not exists\n"
        "market_data.historical_corporate_action_observations" in sql
    )
    assert (
        "create table if not exists\n"
        "market_data.company_action_coverage_observations" in sql
    )
    assert "action_status in ('announced', 'realized', 'cancelled')" in sql
    assert sql.count("in ('verified', 'unresolved', 'conflict')") >= 2
    assert "coverage_completeness in ('complete', 'partial', 'unknown')" in sql
    assert "coverage_result in ('events_present', 'no_events', 'unknown')" in sql
    assert "(coverage_result = 'no_events' and observed_event_count = 0)" in sql
    assert "unsupported_event_count integer not null" in sql
    assert "unresolved_event_count integer not null" in sql
    assert "normalized_event_set_sha256 text not null" in sql
    assert "alter table market_data.corporate_actions" not in sql


def test_lineage_is_complete_and_never_backdates_retrieval_snapshots() -> None:
    sql = _sql(SCHEMA)

    for field in (
        "source_id",
        "source_dataset",
        "source_event_id",
        "source_version",
        "source_revision_hash",
        "source_payload_hash",
        "source_url",
        "source_row",
        "first_observed_at",
        "available_at",
        "available_at_basis",
        "reason_codes",
    ):
        assert sql.count(field) >= 2
    assert sql.count("source_revision_hash ~ '^[0-9a-f]{64}$'") == 2
    assert sql.count("source_payload_hash ~ '^[0-9a-f]{64}$'") == 2
    assert "normalized_event_set_sha256 ~ '^[0-9a-f]{64}$'" in sql
    assert sql.count("jsonb_typeof(source_row) = 'object'") == 2
    assert sql.count("available_at = first_observed_at") == 2
    assert sql.count("available_at <= first_observed_at") == 2
    assert sql.count("'first_observed_at_retrieval'") >= 4


def test_only_complete_timely_verified_coverage_can_pass() -> None:
    sql = _sql(SCHEMA)
    compact = _compact(SCHEMA)

    assert "coverage_resolution_status = 'verified'" in sql
    assert "coverage_completeness = 'complete'" in sql
    assert "coverage_result in ('events_present', 'no_events')" in sql
    assert "and source_row_complete" in sql
    assert "covered_action_types @> array" in sql
    for action_type in (
        "cash_dividend",
        "stock_dividend",
        "split",
        "capital_reduction",
        "rights",
        "other",
    ):
        assert f"'{action_type}'" in sql
    assert "coverage_end_date <= timezone(" in sql
    assert "'asia/taipei', available_at" in sql
    assert "unsupported_event_count = 0" in sql
    assert "unresolved_event_count = 0" in sql
    assert "usage_scope = 'point_in_time_action_coverage'" in sql
    assert "system_status = 'pass'" in sql
    assert "cardinality(reason_codes) = 0" in sql
    assert "usage_scope = 'action_coverage_research_only'" in sql
    assert "system_status in ('research_only', 'fail')" in sql
    assert "cardinality(reason_codes) > 0" in sql
    assert (
        "available_at_basis in ( 'official_publication_at', "
        "'versioned_snapshot' )" in compact
    )


def test_verified_identity_must_match_listing_period_and_effective_dates() -> None:
    sql = _sql(SCHEMA)

    assert "validate_historical_company_action_identity" in sql
    assert "validate_company_action_coverage_identity" in sql
    assert "listing.listing_evidence_id = new.listing_evidence_id" in sql
    assert "listing.listing_period_id = new.listing_period_id" in sql
    assert "listing.security_id = new.security_id" in sql
    assert "listing.listing_market = new.market" in sql
    assert "listing.asset_type = new.asset_type" in sql
    assert "listing.source_symbol = new.source_symbol" in sql
    assert sql.count("listing.available_at <= new.available_at") == 2
    assert "listing.effective_from <= new.ex_date" in sql
    assert "listing.effective_from <= new.coverage_start_date" in sql
    assert "new.coverage_end_date < listing.effective_to" in sql
    assert "historical_company_action_listing_evidence_idx" in sql
    assert "historical_company_action_security_idx" in sql
    assert "company_action_coverage_listing_evidence_idx" in sql
    assert "company_action_coverage_security_idx" in sql


def test_verified_coverage_revisions_remain_append_only_and_queryable() -> None:
    sql = _sql(SCHEMA)

    assert "company_action_coverage_verified_window_uidx" not in sql
    assert "company_action_coverage_revision_uidx" in sql
    assert "source_revision_hash" in sql
    assert "available_at desc" in sql
    assert "where coverage_resolution_status = 'verified'" in sql


def test_event_terms_and_label_eligible_index_fail_closed() -> None:
    sql = _sql(SCHEMA)

    assert "action_status <> 'realized'" in sql
    assert "ex_date <= timezone('asia/taipei', available_at)::date" in sql
    assert "action_type = 'cash_dividend'" in sql
    assert "cash_amount_per_share > 0" in sql
    assert "action_type = 'stock_dividend'" in sql
    assert "share_multiplier = 1 + share_ratio" in sql
    assert "action_type = 'split'" in sql
    assert "action_type = 'capital_reduction'" in sql
    assert "action_type = 'rights'" in sql
    assert "subscription_price_per_share is not null" in sql
    assert "historical_company_action_realized_idx" in sql
    assert "where action_status = 'realized'" in sql
    assert "and source_row_complete" in sql
    assert "and system_status = 'pass'" in sql


def test_both_tables_are_append_only_force_rls_and_service_role_only() -> None:
    sql = _sql(SCHEMA)
    compact = _compact(SCHEMA)
    tables = (
        "historical_corporate_action_observations",
        "company_action_coverage_observations",
    )

    assert sql.count("before update or delete") == 2
    assert "security definer" not in sql
    assert "security invoker" in sql
    assert "create policy" not in sql
    for table in tables:
        assert f"alter table market_data.{table}\nenable row level security" in sql
        assert f"alter table market_data.{table}\nforce row level security" in sql
        assert f"revoke all on market_data.{table}" in sql
        assert f"grant select, insert on market_data.{table} to service_role" in compact
        assert f"grant update on market_data.{table}" not in compact
        assert f"grant delete on market_data.{table}" not in compact

    assert "to anon" not in sql
    assert "to authenticated" not in sql
