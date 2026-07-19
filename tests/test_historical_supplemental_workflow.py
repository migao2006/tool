from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CALLER = ROOT / ".github/workflows/backfill-historical-supplemental.yml"
WORKER = ROOT / ".github/workflows/historical-supplemental-backfill-worker.yml"


def test_schedule_is_feature_gated_until_migration_is_deployed() -> None:
    workflow = CALLER.read_text(encoding="utf-8")

    assert "HISTORICAL_SUPPLEMENTAL_BACKFILL_ENABLED == 'true'" in workflow
    assert workflow.count("if: ${{ vars.HISTORICAL_SUPPLEMENTAL_BACKFILL_ENABLED") == 3
    assert "FINMIND_TOKEN_SECONDARY" in workflow
    assert "FINMIND_TOKEN_TERTIARY" in workflow
    assert "cancel-in-progress: false" in workflow
    assert workflow.count("seed_tasks: true") == 3
    assert "default: institutional_flows,margin_short" in workflow
    assert workflow.count("allowed_datasets:") == 4


def test_worker_archives_to_r2_and_never_embeds_credentials() -> None:
    workflow = WORKER.read_text(encoding="utf-8")

    assert "HISTORICAL_BACKFILL_STORAGE_TARGET: R2" in workflow
    assert "scripts.backfill_historical_supplemental" in workflow
    assert "HISTORICAL_SUPPLEMENTAL_ALLOWED_DATASETS" in workflow
    assert "--start-date 2021-07-19" in workflow
    assert "--end-date 2026-07-17" in workflow
    assert "${{ secrets.finmind_token }}" in workflow
    assert "service_role" not in workflow.lower().replace(
        "supabase_service_role_key", ""
    )
