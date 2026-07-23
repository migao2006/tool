from pathlib import Path

from scripts.check_github_action_pins import reviewed_action_reference


ROOT = Path(__file__).resolve().parents[1]
IMPORT_WORKFLOW = ROOT / ".github/workflows/import-market-data.yml"
DAILY_WORKFLOW = ROOT / ".github/workflows/daily-research-model.yml"
RECOVERY_WORKFLOW = ROOT / ".github/workflows/recover-daily-pipelines.yml"


def test_import_workflow_preserves_sanitized_attempt_result() -> None:
    workflow = IMPORT_WORKFLOW.read_text(encoding="utf-8")

    assert "max_attempts=4" in workflow
    assert "status != 75" in workflow
    assert "delay_seconds=$((attempt * 180))" in workflow
    loop = workflow.index("while (( attempt <= max_attempts ))")
    clear = workflow.index("rm -f import-market-data-result.json", loop)
    invoke = workflow.index("python -m scripts.import_market_data", clear)
    assert loop < clear < invoke
    assert "--result-output import-market-data-result.json" in workflow
    assert "if: always()" in workflow
    assert (
        "name: import-market-data-result-${{ github.run_id }}-${{ github.run_attempt }}"
        in workflow
    )
    assert "path: import-market-data-result.json" in workflow
    assert "if-no-files-found: warn" in workflow
    assert reviewed_action_reference("actions/upload-artifact") in workflow


def test_daily_artifact_dataflow_is_isolated_by_run_attempt() -> None:
    workflow = DAILY_WORKFLOW.read_text(encoding="utf-8")
    names = (
        "daily-research-resolution-${{ github.run_id }}-${{ github.run_attempt }}",
        "daily-bar-publications-${{ github.run_id }}-${{ github.run_attempt }}",
        (
            "daily-research-features-${{ matrix.market }}-${{ github.run_id }}"
            "-${{ github.run_attempt }}"
        ),
        (
            "daily-research-security-catalog-${{ matrix.market }}-${{ github.run_id }}"
            "-${{ github.run_attempt }}"
        ),
        (
            "daily-research-staging-${{ matrix.market }}-${{ github.run_id }}"
            "-${{ github.run_attempt }}"
        ),
        (
            "daily-research-production-${{ matrix.market }}-${{ github.run_id }}"
            "-${{ github.run_attempt }}"
        ),
    )

    for name in names:
        assert name in workflow
    assert "overwrite: true" not in workflow
    assert "rerun-failed-jobs" not in workflow


def test_recovery_workflow_has_exact_privileged_boundary_and_no_recursion() -> None:
    workflow = RECOVERY_WORKFLOW.read_text(encoding="utf-8")

    assert "name: Recover daily pipelines" in workflow
    assert "workflow_run:" in workflow
    assert "- Import market data" in workflow
    assert "- Daily research model" in workflow
    assert "- Recover daily pipelines" not in workflow
    assert "types:" in workflow
    assert "- completed" in workflow
    assert "actions: write" in workflow
    assert "issues: write" in workflow
    assert "contents: read" in workflow
    assert (
        "group: daily-pipeline-recovery-${{ github.event.workflow_run.id }}"
        in workflow
    )
    assert "cancel-in-progress: false" in workflow
    assert "python -m scripts.recover_daily_pipeline" in workflow
    assert "GITHUB_EVENT_PATH: ${{ github.event_path }}" in workflow
    assert "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in workflow
    assert "rerun-failed-jobs" not in workflow
    assert reviewed_action_reference("actions/checkout") in workflow
    assert reviewed_action_reference("actions/setup-python") in workflow
