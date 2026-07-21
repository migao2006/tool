from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "supabase" / "schema" / "011_historical_r2_archive_manifest.sql"
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260718184549_historical_r2_archive_manifest.sql"
)
COUNT_FIX_MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260718185546_fix_historical_archive_home_counts.sql"
)


def _sql(path: Path) -> str:
    return path.read_text(encoding="utf-8").lower()


def test_archive_manifest_is_private_research_only_and_checksum_bound() -> None:
    sql = _sql(SCHEMA)

    assert "create table if not exists market_data.historical_archive_objects" in sql
    assert "storage_provider = 'cloudflare_r2'" in sql
    assert "point_in_time_status = 'unverified'" in sql
    assert "usage_scope = 'raw_landing_only'" in sql
    assert "system_status = 'research_only'" in sql
    assert "source_payload_hash ~ '^[0-9a-f]{64}$'" in sql
    assert "parquet_sha256 ~ '^[0-9a-f]{64}$'" in sql
    assert "scheduled_market in ('twse', 'tpex')" in sql
    assert "enable row level security" in sql
    assert "revoke all on market_data.historical_archive_objects" in sql
    assert "grant select, insert, update" in sql
    assert "to service_role" in sql


def test_archive_migration_keeps_home_counts_without_double_counting() -> None:
    sql = _sql(MIGRATION)

    assert "rename to refresh_home_data_status_without_archive" in sql
    assert "perform market_data.refresh_home_data_status_without_archive()" in sql
    assert "sum(row_count)" in sql
    assert "sum(parsed_row_count)" in sql
    assert "sum(quarantined_row_count)" in sql
    assert "requested_end_date" in sql
    assert "where not exists" in sql
    assert "archive.source_payload_hash = landing.source_payload_hash" in sql
    assert "historical_point_in_time_unverified" in sql
    assert "revoke all on function market_data.refresh_home_data_status()" in sql
    assert "grant execute on function market_data.refresh_home_data_status()" in sql


def test_count_fix_replaces_wrapper_with_latest_logical_slice_counting() -> None:
    sql = _sql(COUNT_FIX_MIGRATION)

    assert "create or replace function market_data.refresh_home_data_status()" in sql
    assert "with latest_archive_slice as" in sql
    assert "select distinct on" in sql
    assert "source_symbol" in sql
    assert "requested_start_date" in sql
    assert "requested_end_date" in sql
    assert "created_at desc" in sql
    assert "archive_id desc" in sql
    assert "select market_data.refresh_home_data_status()" in sql
