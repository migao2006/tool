from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/publish-tpex-latest-research-snapshot.yml"


def test_tpex_daily_publish_is_environment_scoped_and_scheduled_after_benchmark() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "0 13 * * 1-5"' in workflow
    assert "target_environment:" in workflow
    assert "- staging" in workflow
    assert "- production" in workflow
    assert (
        "environment: ${{ github.event_name == 'schedule' && 'staging' || "
        "inputs.target_environment }}" in workflow
    )
    assert "SUPABASE_PROJECT_REF: ${{ vars.SUPABASE_PROJECT_REF }}" in workflow
    assert "SUPABASE_URL: ${{ vars.SUPABASE_URL }}" in workflow
    assert "SUPABASE_URL: ${{ secrets.SUPABASE_URL }}" not in workflow
    assert (
        "SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}"
        in workflow
    )
    assert "ALPHA_LENS_TARGET_ENVIRONMENT: ${{" in workflow
    assert "RESEARCH_PREDICTION_PRODUCTION_PUBLISH_ENABLED: ${{" in workflow
    assert 'test "$GITHUB_EVENT_NAME" = "workflow_dispatch"' in workflow
    assert 'test "$ALPHA_LENS_TARGET_ENVIRONMENT" = "staging"' in workflow
    assert 'test "$RESEARCH_PREDICTION_PRODUCTION_PUBLISH_ENABLED" = "true"' in workflow
    assert 'test "$RESEARCH_PREDICTION_PRODUCTION_PUBLISH_ENABLED" = "false"' in workflow
    assert "TPEX_DAILY_RESEARCH_PREDICTION_ENABLED == 'true'" in workflow
    assert '"https://${SUPABASE_PROJECT_REF}.supabase.co"' in workflow
    assert "Supabase URL does not match the selected project ref" in workflow


def test_tpex_daily_publish_authenticates_exact_artifact_producers() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert ".github/workflows/build-tpex-prepared-research-dataset.yml" in workflow
    assert ".github/workflows/build-tpex-research-feature-dataset.yml" in workflow
    assert '"$conclusion" != "success"' in workflow
    assert '"$head_branch" != "main"' in workflow
    assert 'git merge-base --is-ancestor "$head_sha" "$GITHUB_SHA"' in workflow
    assert '"$repository" != "$GITHUB_REPOSITORY"' in workflow
    assert '"$head_repository" != "$GITHUB_REPOSITORY"' in workflow
    assert '"$event" != "workflow_dispatch"' in workflow
    assert "gh api --paginate" in workflow
    assert "^sha256:[0-9a-f]{64}$" in workflow
    assert workflow.count("uses: actions/download-artifact@v8") == 2
    assert workflow.count("digest-mismatch: error") == 2
    assert "artifact-ids: ${{ env.PREPARED_ARTIFACT_ID }}" in workflow
    assert "artifact-ids: ${{ env.FEATURE_ARTIFACT_ID }}" in workflow
    assert "TPEX_PREPARED_SOURCE_RUN_ID=$prepared_run_id" in workflow
    assert "TPEX_PREPARED_SOURCE_RUN_SHA=$prepared_run_sha" in workflow
    assert "TPEX_PREPARED_SOURCE_ARTIFACT_ID=$prepared_artifact_id" in workflow
    assert "TPEX_PREPARED_SOURCE_ARTIFACT_DIGEST=$prepared_artifact_digest" in workflow
    assert "TPEX_FEATURE_SOURCE_ARTIFACT_ID=$feature_artifact_id" in workflow
    assert "TPEX_FEATURE_SOURCE_ARTIFACT_DIGEST=$feature_artifact_digest" in workflow


def test_tpex_daily_publish_fails_closed_on_stale_features() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "REQUESTED_AS_OF_DATE: ${{ inputs.as_of_date }}" in workflow
    assert '"$GITHUB_EVENT_NAME" == "schedule"' in workflow
    assert 'required_as_of_date="$(TZ=Asia/Taipei date +%F)"' in workflow
    assert '"$REQUESTED_AS_OF_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$' in workflow
    assert 'date -u -d "$REQUESTED_AS_OF_DATE" +%F' in workflow
    assert 'echo "REQUIRED_AS_OF_DATE=$required_as_of_date"' in workflow
    assert '--required-as-of-date "$REQUIRED_AS_OF_DATE"' in workflow
    assert "scripts.publish_tpex_daily_research_snapshot" in workflow
    assert "publish_twse_daily_research_snapshot" not in workflow


def test_dispatch_inputs_only_reach_shell_through_environment_variables() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "REQUESTED_PREPARED_RUN_ID: ${{ inputs.prepared_run_id }}" in workflow
    assert "REQUESTED_FEATURE_RUN_ID: ${{ inputs.feature_run_id }}" in workflow
    assert "REQUESTED_AS_OF_DATE: ${{ inputs.as_of_date }}" in workflow
    run_blocks = workflow.split("run:")[1:]
    assert all(
        "${{ inputs." not in block.split("\n      - name:", 1)[0]
        for block in run_blocks
    )
