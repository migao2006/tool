from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/publish-tpex-latest-research-snapshot.yml"


def test_tpex_daily_publish_is_staging_scoped_and_scheduled_after_benchmark() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "0 13 * * 1-5"' in workflow
    assert "environment: staging" in workflow
    assert "ALPHA_LENS_TARGET_ENVIRONMENT: staging" in workflow
    assert 'RESEARCH_PREDICTION_PRODUCTION_PUBLISH_ENABLED: "false"' in workflow
    assert "TPEX_DAILY_RESEARCH_PREDICTION_ENABLED == 'true'" in workflow


def test_tpex_daily_publish_authenticates_exact_artifact_producers() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert ".github/workflows/build-tpex-prepared-research-dataset.yml" in workflow
    assert ".github/workflows/build-tpex-research-feature-dataset.yml" in workflow
    assert '"$conclusion" != "success" || "$head_branch" != "main"' in workflow
    assert 'git merge-base --is-ancestor "$head_sha" origin/main' in workflow
    assert "tpex-prepared-research-${{ env.PREPARED_RUN_ID }}" in workflow
    assert "tpex-research-features-${{ env.FEATURE_RUN_ID }}" in workflow


def test_tpex_daily_publish_fails_closed_on_stale_features() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'REQUIRED_AS_OF_DATE=$(TZ=Asia/Taipei date +%F)' in workflow
    assert '--required-as-of-date "$REQUIRED_AS_OF_DATE"' in workflow
    assert "scripts.publish_tpex_daily_research_snapshot" in workflow
    assert "publish_twse_daily_research_snapshot" not in workflow


def test_dispatch_inputs_only_reach_shell_through_environment_variables() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "REQUESTED_PREPARED_RUN_ID: ${{ inputs.prepared_run_id }}" in workflow
    assert "REQUESTED_FEATURE_RUN_ID: ${{ inputs.feature_run_id }}" in workflow
    run_blocks = workflow.split("run:")[1:]
    assert all(
        "${{ inputs." not in block.split("\n      - name:", 1)[0]
        for block in run_blocks
    )
