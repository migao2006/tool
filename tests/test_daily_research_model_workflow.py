from pathlib import Path

from scripts.check_github_action_pins import reviewed_action_reference


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/daily-research-model.yml"


def test_daily_model_is_triggered_after_import_with_a_fallback_schedule() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "push:" in workflow
    assert "branches:" in workflow
    assert "- main" in workflow
    assert "- .github/workflows/daily-research-model.yml" in workflow
    assert "workflow_run:" in workflow
    assert "- Import market data" in workflow
    assert 'cron: "15 13 * * 1-5"' in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
    assert "concurrency:" in workflow
    assert "group: daily-research-model" in workflow
    assert "cancel-in-progress: false" in workflow


def test_daily_model_publishes_current_bars_and_requires_one_exact_date() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "scripts.resolve_daily_research_date" in workflow
    assert "--max-age-days 14" in workflow
    assert "scripts.publish_daily_bar_publication_snapshots" in workflow
    assert "--include-current-publication" in workflow
    assert '--required-as-of-date "$TARGET_DATE"' in workflow
    assert (
        "daily-research-features-${{ matrix.market }}-${{ github.run_id }}"
        "-${{ github.run_attempt }}"
        in workflow
    )
    assert "fromJSON(needs.resolve.outputs.markets)" in workflow


def test_daily_model_uses_staging_first_then_identical_production_snapshot() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    staging = workflow.index("publish-staging:")
    production = workflow.index("publish-production:")
    assert staging < production
    assert "environment: staging" in workflow
    assert "environment: production" in workflow
    assert "scripts.verify_daily_research_publish" in workflow
    assert "scripts.publish_stored_research_snapshot" in workflow
    assert "Download Staging-verified immutable snapshot" in workflow
    assert "DAILY_RESEARCH_PRODUCTION_PUBLISH_ENABLED != 'false'" in workflow
    assert 'RESEARCH_PREDICTION_PRODUCTION_PUBLISH_ENABLED: "false"' in workflow
    assert 'RESEARCH_PREDICTION_PRODUCTION_PUBLISH_ENABLED: "true"' in workflow


def test_daily_model_syncs_sanitized_market_identity_before_staging_inference() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    build = workflow.index("build-features:")
    feature_upload = workflow.index("Preserve exact-date feature artifact", build)
    catalog_job = workflow.index("export-security-catalog:")
    export = workflow.index("scripts.export_research_security_catalog", catalog_job)
    catalog_upload = workflow.index("Preserve immutable security catalog", catalog_job)
    staging = workflow.index("publish-staging:")
    feature_download = workflow.index(
        "Download exact-date feature artifact from this workflow", staging
    )
    catalog_download = workflow.index(
        "Download immutable Production security catalog", staging
    )
    sync = workflow.index("scripts.sync_research_security_catalog", staging)
    inference = workflow.index(
        "Train and publish exact-date snapshot to Staging", staging
    )

    assert build < feature_upload < catalog_job < export < catalog_upload < staging
    assert staging < feature_download < catalog_download < sync < inference
    assert "environment: production" in workflow[catalog_job:staging]
    assert "- export-security-catalog" in workflow[staging:inference]
    assert "Supabase URL does not match Production project ref" in workflow
    assert "--market \"$MARKET\"" in workflow
    assert (
        "--output \"research-security-catalog/${slug}-research-security-catalog.json\""
        in workflow
    )
    assert (
        "--catalog \"inputs/security-catalog/${slug}-research-security-catalog.json\""
        in workflow
    )


def test_daily_model_authenticates_prepared_artifacts_and_pins_actions() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "build-twse-prepared-research-dataset.yml" in workflow
    assert "build-tpex-prepared-research-dataset.yml" in workflow
    assert 'git merge-base --is-ancestor "$head_sha" origin/main' in workflow
    assert '"$repository" != "$GITHUB_REPOSITORY"' in workflow
    assert '"$head_repository" != "$GITHUB_REPOSITORY"' in workflow
    assert "^sha256:[0-9a-f]{64}$" in workflow
    assert "TPEX_PREPARED_SOURCE_RUN_ID: ${{ steps.prepared.outputs.run_id }}" in workflow
    assert "TPEX_PREPARED_SOURCE_RUN_SHA: ${{ steps.prepared.outputs.head_sha }}" in workflow
    assert reviewed_action_reference("actions/checkout") in workflow
    assert reviewed_action_reference("actions/setup-python") in workflow
    assert reviewed_action_reference("astral-sh/setup-uv") in workflow
    assert reviewed_action_reference("actions/upload-artifact") in workflow
    assert reviewed_action_reference("actions/download-artifact") in workflow
