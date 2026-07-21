from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/backfill-historical-benchmark.yml"


def test_workflow_is_disabled_by_default_and_uses_one_finmind_token() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "HISTORICAL_BENCHMARK_BACKFILL_ENABLED == 'true'" in workflow
    assert workflow.count("FINMIND_TOKEN:") == 1
    assert "FINMIND_TOKEN_SECONDARY" not in workflow
    assert "FINMIND_TOKEN_TERTIARY" not in workflow
    assert "scripts.backfill_historical_benchmark" in workflow
    assert "HISTORICAL_BACKFILL_STORAGE_TARGET: R2" in workflow
    assert "cancel-in-progress: false" in workflow


def test_workflow_does_not_invoke_current_month_benchmark_import() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "scripts.import_benchmarks" not in workflow
    assert "fetch_quota" not in workflow
