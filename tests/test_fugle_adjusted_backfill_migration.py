from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260719104409_add_fugle_adjusted_backfill_control.sql"
)
ROLLBACK = (
    ROOT / "supabase" / "snippets" / "rollback_fugle_adjusted_backfill_control.sql"
)
VALIDATION = (
    ROOT / "supabase" / "snippets" / "validate_fugle_adjusted_backfill_control.sql"
)


def _sql(path: Path) -> str:
    return path.read_text(encoding="utf-8").lower()


def test_archive_allowlist_preserves_exact_provider_dataset_pairs() -> None:
    sql = _sql(MIGRATION)

    assert "provider_code = 'finmind'" in sql
    assert "provider_code = 'twse'" in sql
    assert "source_dataset = 'taiex_price_index_ohlc'" in sql
    assert "provider_code = 'fugle'" in sql
    assert "source_dataset = 'adjusted_bars'" in sql
    assert "schema_version = 'historical_adjusted_bars.v1'" in sql
    assert "scheduled_market = 'twse'" in sql
    assert "asset_type = 'common_stock'" in sql
    assert "source_symbol ~ '^[1-9][0-9]{3}$'" in sql
    assert "provider_code in" not in sql
    assert "add constraint historical_archive_scope_check_fugle" in sql
    assert "validate constraint historical_archive_scope_check_fugle" in sql


def test_fugle_seed_is_isolated_and_chunks_to_366_inclusive_days() -> None:
    sql = _sql(MIGRATION)

    assert "seed_historical_fugle_adjusted_twse_tasks" in sql
    assert "generate_series" in sql
    assert "interval '366 days'" in sql
    assert "chunk_start::date + 365" in sql
    assert "security.market = 'twse'" in sql
    assert "security.asset_type = 'common_stock'" in sql
    assert "'fugle',\n        'adjusted_bars'" in sql
    assert "'request_universe_not_point_in_time'" in sql
    assert "'raw_landing_only'" in sql


def test_claim_and_snapshot_never_share_finmind_adjusted_tasks() -> None:
    sql = _sql(MIGRATION)

    assert "claim_historical_fugle_adjusted_backfill_task" in sql
    assert "historical_fugle_adjusted_backfill_snapshot" in sql
    assert sql.count("provider_code = 'fugle'") >= 8
    assert sql.count("source_dataset = 'adjusted_bars'") >= 8
    assert "grant execute on function" in sql
    assert "to service_role" in sql
    assert "from public, anon, authenticated" in sql
    assert "security invoker" in sql


def test_local_validation_and_rollback_are_bounded_and_reversible() -> None:
    validation = _sql(VALIDATION)
    rollback = _sql(ROLLBACK)

    assert "rollback;" in validation
    assert "max_inclusive_days > 366" in validation
    assert "wrong_scope_count != 0" in validation
    assert "drop function if exists" in rollback
    assert "drop index if exists" in rollback
    assert "rollback blocked: fugle tasks or archive records exist" in rollback
    assert "provider_code = 'finmind'" in rollback
    assert "provider_code = 'twse'" in rollback
    assert "source_dataset = 'taiex_price_index_ohlc'" in rollback
    assert "provider_code = 'fugle'" in rollback
    assert "historical_archive_scope_check_rollback" in rollback
    assert "validate constraint historical_archive_scope_check_rollback" in rollback
