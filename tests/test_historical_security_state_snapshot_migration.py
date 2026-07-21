from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (
    ROOT
    / "supabase"
    / "schema"
    / "016_historical_security_state_snapshots.sql"
)
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260719061000_historical_security_state_snapshots.sql"
)


def _sql(path: Path) -> str:
    return path.read_text(encoding="utf-8").lower()


def _compact(path: Path) -> str:
    return " ".join(_sql(path).split())


def test_schema_and_versioned_migration_are_identical() -> None:
    assert _sql(SCHEMA) == _sql(MIGRATION)


def test_verified_snapshot_requires_every_critical_state() -> None:
    sql = _sql(SCHEMA)

    assert "create table if not exists market_data.security_state_snapshots" in sql
    assert "fully_observed_row_count + unknown_state_row_count = row_count" in sql
    assert "unknown_state_row_count = 0" in sql
    assert "fully_observed_row_count = row_count" in sql
    for field in (
        "trading_status",
        "attention_flag",
        "disposition_flag",
        "altered_trading_method_flag",
        "full_cash_delivery_flag",
        "periodic_auction_flag",
        "suspended_flag",
    ):
        assert f"'{field}'" in sql
    assert "absence from an event list never proves" in sql
    assert "usage_scope = 'point_in_time_security_state'" in sql
    assert "usage_scope = 'security_state_research_only'" in sql
    assert "coverage_end_date <= timezone(" in sql
    assert "'asia/taipei', available_at" in sql


def test_snapshot_lineage_cannot_backdate_first_observation() -> None:
    sql = _sql(SCHEMA)

    assert "source_revision_hash ~ '^[0-9a-f]{64}$'" in sql
    assert "source_payload_hash ~ '^[0-9a-f]{64}$'" in sql
    assert "normalized_content_sha256 ~ '^[0-9a-f]{64}$'" in sql
    assert "available_at_basis = 'official_publication_at'" in sql
    assert "available_at = published_at" in sql
    assert "available_at_basis = 'versioned_snapshot'" in sql
    assert "available_at = first_observed_at" in sql
    assert "available_at_basis = 'first_observed_at_retrieval'" in sql
    assert "research-only and is never backdated" in sql


def test_snapshot_is_append_only_private_and_indexed() -> None:
    sql = _sql(SCHEMA)
    compact = _compact(SCHEMA)

    assert "before update or delete" in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "revoke all on market_data.security_state_snapshots" in sql
    assert (
        "grant select, insert on market_data.security_state_snapshots "
        "to service_role"
    ) in compact
    assert "grant update on market_data.security_state_snapshots" not in sql
    assert "grant delete on market_data.security_state_snapshots" not in sql
    assert "security_state_snapshots_revision_uidx" in sql
    assert "security_state_snapshots_verified_coverage_uidx" not in sql
    assert "security_state_snapshots_revision_uidx" in sql
    assert "security_state_snapshots_lookup_idx" in sql
    assert "available_at desc" in sql
