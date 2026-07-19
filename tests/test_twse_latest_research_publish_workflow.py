from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/publish-twse-latest-research-snapshot.yml"


def test_latest_research_publish_is_main_only_and_explicitly_gated() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'test "$GITHUB_REF" = "refs/heads/main"' in workflow
    assert "TWSE_DAILY_RESEARCH_PREDICTION_ENABLED == 'true'" in workflow
    assert 'ALPHA_LENS_TARGET_ENVIRONMENT: production' in workflow
    assert '--publish-supabase' in workflow


def test_latest_research_publish_uses_verified_prepared_and_v2_feature_inputs() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "twse-prepared-research-${{ env.PREPARED_RUN_ID }}" in workflow
    assert "twse-research-features-${{ env.FEATURE_RUN_ID }}" in workflow
    assert "--prepared-audit inputs/prepared/twse-prepared-research-audit.json" in workflow
    assert "--feature-audit inputs/features/twse-research-features-audit.json" in workflow
    assert "artifacts/**/*" in workflow


def test_artifact_runs_are_authenticated_before_download() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    verification = workflow.index("Verify artifact-producing workflow runs")
    prepared_download = workflow.index("Download verified prepared research dataset")

    assert verification < prepared_download
    assert 'repos/${GITHUB_REPOSITORY}/actions/runs/${run_id}' in workflow
    assert '.github/workflows/build-twse-prepared-research-dataset.yml' in workflow
    assert '.github/workflows/build-twse-research-feature-dataset.yml' in workflow
    assert '"$conclusion" != "success"' in workflow
    assert '"$head_branch" != "main"' in workflow
    assert 'git merge-base --is-ancestor "$head_sha" origin/main' in workflow
    assert "fetch-depth: 0" in workflow


def test_dispatch_inputs_only_reach_shell_through_environment_variables() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "PREPARED_RUN_ID: ${{ inputs.prepared_run_id }}" in workflow
    assert "FEATURE_RUN_ID: ${{ inputs.feature_run_id }}" in workflow
    assert '"$PREPARED_RUN_ID"' in workflow
    assert '"$FEATURE_RUN_ID"' in workflow
    assert '[[ ! "$run_id" =~ ^[1-9][0-9]*$ ]]' in workflow

    run_blocks = workflow.split("run:")[1:]
    assert all("${{ inputs." not in block.split("\n      - name:", 1)[0] for block in run_blocks)
