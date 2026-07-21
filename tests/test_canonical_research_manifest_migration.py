from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "supabase" / "schema" / "014_canonical_research_manifests.sql"
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260719060000_canonical_research_manifests.sql"
)


def _sql(path: Path) -> str:
    return path.read_text(encoding="utf-8").lower()


def _compact(path: Path) -> str:
    return " ".join(_sql(path).split())


def test_schema_reference_matches_versioned_migration() -> None:
    assert _sql(SCHEMA) == _sql(MIGRATION)


def test_daily_bar_publication_snapshot_keeps_rows_in_private_r2() -> None:
    sql = _sql(SCHEMA)

    assert "create table if not exists market_data.daily_bar_publication_snapshots" in sql
    assert "storage_provider = 'cloudflare_r2'" in sql
    assert "parquet_sha256 ~ '^[0-9a-f]{64}$'" in sql
    assert "normalized_content_sha256 ~ '^[0-9a-f]{64}$'" in sql
    assert "byte_size > 0" in sql
    assert "row_count > 0" in sql
    assert "provider_code = market" in sql
    assert "source_revision_hash ~ '^[0-9a-f]{64}$'" in sql
    assert "source_payload_hash ~ '^[0-9a-f]{64}$'" in sql
    assert "jsonb_typeof(source_metadata) = 'object'" in sql
    assert "open_price" not in sql
    assert "close_price" not in sql


def test_verified_publication_evidence_cannot_use_retrieval_time_basis() -> None:
    sql = _compact(SCHEMA)

    assert "verification_status in ('verified', 'unresolved', 'conflict')" in sql
    assert (
        "verification_status = 'verified' and available_at_basis in "
        "( 'official_publication_at', 'versioned_snapshot' )"
    ) in sql
    assert "usage_scope = 'point_in_time_daily_bar'" in sql
    assert "system_status = 'pass'" in sql
    assert "cardinality(reason_codes) = 0" in sql
    assert "trading_date <= timezone(" in sql
    assert "'asia/taipei', available_at" in sql
    assert "usage_scope = 'bar_publication_research_only'" in sql
    assert "system_status in ('research_only', 'fail')" in sql
    assert "cardinality(reason_codes) > 0" in sql
    assert (
        "available_at_basis = 'first_observed_at_retrieval' "
        "and published_at is null and available_at = first_observed_at"
    ) in sql
    assert "daily_bar_publication_snapshots_verified_session_uidx" not in sql
    assert "daily_bar_publication_snapshots_revision_uidx" in sql
    assert "available_at desc" in sql


def test_canonical_manifest_is_bound_to_raw_and_audited_snapshots() -> None:
    sql = _sql(SCHEMA)

    assert "create table if not exists market_data.canonical_dataset_objects" in sql
    assert "references market_data.historical_archive_objects (archive_key)" in sql
    assert "raw_parquet_sha256 ~ '^[0-9a-f]{64}$'" in sql
    assert "raw_manifest_snapshot_sha256 ~ '^[0-9a-f]{64}$'" in sql
    assert "build_input_snapshot_sha256 ~ '^[0-9a-f]{64}$'" in sql
    for snapshot in (
        "identity_snapshot_sha256",
        "calendar_snapshot_sha256",
        "security_state_snapshot_sha256",
        "company_action_snapshot_sha256",
    ):
        assert snapshot in sql
    assert "publication_snapshot_id bigint" in sql
    assert "canonical_dataset_objects_publication_snapshot_idx" in sql
    assert "where publication_snapshot_id is not null" in sql
    assert "publication_rule_version text not null" in sql
    assert "builder_version text not null" in sql
    assert "git_commit text not null" in sql
    assert "horizon = 5" in sql
    assert "validate_canonical_dataset_raw_archive" in sql
    assert "raw_archive.parquet_sha256 <> new.raw_parquet_sha256" in sql
    assert "raw_archive.scheduled_market <> new.market" in sql
    assert "raw_archive.usage_scope <> 'raw_landing_only'" in sql


def test_raw_only_canonical_contract_cannot_claim_model_eligibility() -> None:
    sql = _sql(SCHEMA)

    assert "research_only_row_count = canonical_row_count" in sql
    assert sql.count("model_eligible_row_count = 0") >= 2
    assert "point_in_time_status = 'unverified'" in sql
    assert "usage_scope = 'canonical_research_only'" in sql
    assert "system_status = 'research_only'" in sql
    assert "cardinality(reason_codes) > 0" in sql
    assert "source_row_count = canonical_row_count + rejected_row_count" in sql
    assert "quarantined_row_count <= rejected_row_count" in sql
    assert "usage_scope = 'model_eligible'" not in sql


def test_both_manifests_are_append_only_force_rls_and_service_role_only() -> None:
    sql = _sql(SCHEMA)
    compact_sql = _compact(SCHEMA)

    assert sql.count("before update or delete") == 2
    assert "security definer" not in sql
    for table in (
        "daily_bar_publication_snapshots",
        "canonical_dataset_objects",
    ):
        assert f"alter table market_data.{table}" in sql
        assert f"market_data.{table} enable row level security" in compact_sql
        assert f"market_data.{table} force row level security" in compact_sql
        assert f"revoke all on market_data.{table}" in sql
        assert f"grant select, insert on market_data.{table}" in compact_sql
        assert f"grant update on market_data.{table}" not in compact_sql
        assert f"grant delete on market_data.{table}" not in compact_sql

    assert "create policy" not in sql
    assert "to anon" not in sql
    assert "to authenticated" not in sql
