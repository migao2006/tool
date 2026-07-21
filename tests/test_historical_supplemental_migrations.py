from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
EXPAND = (
    ROOT
    / "supabase/migrations/20260719044435_expand_historical_supplemental_archives.sql"
)
CLAIMS = (
    ROOT
    / "supabase/migrations/20260719045214_isolate_historical_supplemental_claims.sql"
)
SNAPSHOTS = (
    ROOT
    / "supabase/migrations/20260719045216_separate_historical_backfill_snapshots.sql"
)
FREE_TIER = (
    ROOT
    / "supabase/migrations/20260719081157_defer_unavailable_supplemental_datasets.sql"
)


def test_archive_manifest_allows_only_explicit_versioned_datasets() -> None:
    sql = EXPAND.read_text(encoding="utf-8")

    for dataset in (
        "daily_bars",
        "adjusted_bars",
        "institutional_flows",
        "margin_short",
    ):
        assert f"'{dataset}'" in sql
    for schema in (
        "historical_daily_bars.v1",
        "historical_adjusted_bars.v1",
        "historical_institutional_flows.v1",
        "historical_margin_short.v1",
    ):
        assert f"'{schema}'" in sql
    assert "point_in_time_status = 'UNVERIFIED'" in sql
    assert "usage_scope = 'RAW_LANDING_ONLY'" in sql
    assert "system_status = 'RESEARCH_ONLY'" in sql


def test_supplemental_queue_is_twse_only_and_daily_claim_is_isolated() -> None:
    expand = EXPAND.read_text(encoding="utf-8")
    claims = CLAIMS.read_text(encoding="utf-8")
    snapshots = SNAPSHOTS.read_text(encoding="utf-8")

    assert "security.market = 'TWSE'" in expand
    assert "security.asset_type = 'COMMON_STOCK'" in expand
    assert "when 'adjusted_bars' then 10" in claims
    assert "when 'institutional_flows' then 20" in claims
    assert "when 'margin_short' then 30" in claims
    assert "expired.source_dataset = 'daily_bars'" in claims
    assert "queued.source_dataset = 'daily_bars'" in claims
    assert "tasks.source_dataset = 'daily_bars'" in snapshots


def test_new_internal_rpcs_remain_service_role_only() -> None:
    sql = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (EXPAND, CLAIMS, SNAPSHOTS, FREE_TIER)
    )

    assert sql.count("from public, anon, authenticated") >= 3
    assert sql.count("to service_role") >= 3


def test_free_tier_claim_defers_adjusted_bars_without_exhausting_it() -> None:
    sql = FREE_TIER.read_text(encoding="utf-8")

    assert re.search(r"p_allowed_datasets text\s*\[\]\s+default array\[", sql)
    assert "p_allowed_datasets is null" in sql
    assert "'institutional_flows'" in sql
    assert "'margin_short'" in sql
    assert "'adjusted_bars' = any(p_allowed_datasets)" in sql
    assert "next_attempt_at = 'infinity'::timestamptz" in sql
    assert "ADJUSTED_BARS_PROVIDER_ACCESS_UNAVAILABLE" in sql
    assert "FINMIND_DATASET_ACCESS_UNAVAILABLE" in sql
    assert "PROVIDER_ACCESS_RESTORED" in sql
    assert "enabled.status in ('RETRY', 'EXHAUSTED')" in sql
    assert "attempt_count = 0" in sql
    assert "and not (" in sql
    assert "source_dataset = any(p_allowed_datasets)" in sql
    assert "array_position(p_allowed_datasets, queued.source_dataset)" in sql
    assert "status = 'SUCCEEDED'" not in sql
    assert "delete from" not in sql.lower()
