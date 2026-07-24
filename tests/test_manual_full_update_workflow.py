from pathlib import Path

from scripts.check_github_action_pins import reviewed_action_reference


ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / ".github/workflows/manual-full-update.yml"
IMPORT = ROOT / ".github/workflows/import-market-data.yml"
DAILY = ROOT / ".github/workflows/daily-research-model.yml"
RECOVERY = ROOT / ".github/workflows/recover-daily-pipelines.yml"


def test_manual_full_update_has_one_dispatch_only_entry_with_safe_defaults() -> None:
    workflow = MANUAL.read_text(encoding="utf-8")
    trigger_block = workflow[workflow.index("on:") : workflow.index("permissions:")]

    assert "workflow_dispatch:" in trigger_block
    assert "schedule:" not in trigger_block
    assert "push:" not in trigger_block
    assert "workflow_run:" not in trigger_block
    assert "workflow_call:" not in trigger_block
    assert "dry_run:" in trigger_block
    assert "publish_production:" in trigger_block
    assert "as_of_date:" in trigger_block
    assert "default: false" in trigger_block
    assert "default: true" in trigger_block
    assert 'default: ""' in trigger_block


def test_manual_full_update_requires_main_and_reuses_both_workflows() -> None:
    workflow = MANUAL.read_text(encoding="utf-8")

    assert 'GITHUB_REF_VALUE" != "refs/heads/main"' in workflow
    assert "date.fromisoformat(value).isoformat() != value" in workflow
    assert "uses: ./.github/workflows/import-market-data.yml" in workflow
    assert "uses: ./.github/workflows/daily-research-model.yml" in workflow
    assert "needs:" in workflow
    assert "- import" in workflow
    assert "manual_full_update: true" in workflow
    assert "dry_run: ${{ inputs.dry_run }}" in workflow
    assert "publish_production: ${{ inputs.publish_production }}" in workflow
    assert workflow.count("as_of_date: ${{ inputs.as_of_date }}") == 1
    assert "scripts.import_market_data" not in workflow
    assert "scripts.resolve_daily_research_date" not in workflow
    assert "scripts.publish_stored_research_snapshot" not in workflow


def test_manual_and_called_workflows_keep_distinct_serial_mutation_boundaries() -> None:
    manual = MANUAL.read_text(encoding="utf-8")
    imported = IMPORT.read_text(encoding="utf-8")
    daily = DAILY.read_text(encoding="utf-8")

    assert "group: manual-full-update" in manual
    assert "group: import-market-data" in imported
    assert "group: daily-research-model" in daily
    assert "cancel-in-progress: false" in manual
    assert "cancel-in-progress: false" in imported
    assert "cancel-in-progress: false" in daily


def test_manual_summary_is_always_fail_closed_and_attempt_qualified() -> None:
    workflow = MANUAL.read_text(encoding="utf-8")

    assert "name: Final verification and summary" in workflow
    assert "if: always()" in workflow
    assert "scripts.summarize_manual_full_update" in workflow
    assert "--preflight-result \"${{ needs.preflight.result }}\"" in workflow
    assert "--import-job-result \"${{ needs.import.result }}\"" in workflow
    assert "--research-job-result \"${{ needs.research.result }}\"" in workflow
    assert "$GITHUB_STEP_SUMMARY" in workflow
    for evidence_name in (
        "import-market-data-result-${{ github.run_id }}-${{ github.run_attempt }}",
        "daily-research-resolution-${{ github.run_id }}-${{ github.run_attempt }}",
        "daily-research-production-TWSE-${{ github.run_id }}-${{ github.run_attempt }}",
        "daily-research-production-TPEX-${{ github.run_id }}-${{ github.run_attempt }}",
        "manual-full-update-summary-${{ github.run_id }}-${{ github.run_attempt }}",
    ):
        assert evidence_name in workflow
    assert "digest-mismatch: error" in workflow
    assert "permissions:" in workflow
    assert "actions: read" in workflow
    assert "contents: read" in workflow
    assert reviewed_action_reference("actions/checkout") in workflow
    assert reviewed_action_reference("actions/setup-python") in workflow
    assert reviewed_action_reference("actions/download-artifact") in workflow
    assert reviewed_action_reference("actions/upload-artifact") in workflow


def test_existing_recovery_explicitly_monitors_the_manual_wrapper() -> None:
    recovery = RECOVERY.read_text(encoding="utf-8")

    assert "- Manual full update" in recovery
    assert "actions: write" in recovery
    assert "issues: write" in recovery
    assert "python -m scripts.recover_daily_pipeline" in recovery
