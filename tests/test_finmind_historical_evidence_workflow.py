from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CALLER = ROOT / ".github/workflows/backfill-finmind-historical-evidence.yml"
WORKER = ROOT / ".github/workflows/finmind-historical-evidence-worker.yml"


def test_evidence_schedule_is_off_until_explicitly_enabled() -> None:
    workflow = CALLER.read_text(encoding="utf-8")

    gate = "FINMIND_HISTORICAL_EVIDENCE_ENABLED == 'true'"
    assert workflow.count(gate) == 3
    assert "cancel-in-progress: false" in workflow
    assert "FINMIND_TOKEN_SECONDARY" in workflow
    assert "FINMIND_TOKEN_TERTIARY" in workflow


def test_only_primary_credential_fetches_global_datasets() -> None:
    workflow = CALLER.read_text(encoding="utf-8")

    assert workflow.count("include_global: true") == 1
    assert workflow.count("include_global: false") == 2
    assert "shard_index: 0" in workflow
    assert "shard_index: 1" in workflow
    assert "shard_index: 2" in workflow
    assert "secrets: inherit" not in workflow


def test_worker_is_quota_bounded_and_auditable() -> None:
    workflow = WORKER.read_text(encoding="utf-8")

    assert "--quota-reserve 30" in workflow
    assert "--pacing-seconds 7.5" in workflow
    assert "--defer-on-quota" in workflow
    assert "scripts.backfill_finmind_historical_evidence" in workflow
    assert "retention-days: 90" in workflow
    assert "${{ secrets.finmind_token }}" in workflow
    assert "service_role" not in workflow.lower().replace(
        "supabase_service_role_key", ""
    )


def test_untrusted_dispatch_strings_are_not_interpolated_into_secret_shell() -> None:
    workflow = WORKER.read_text(encoding="utf-8")

    assert "START_DATE: ${{ inputs.start_date }}" in workflow
    assert "END_DATE: ${{ inputs.end_date }}" in workflow
    assert '--start-date "$START_DATE"' in workflow
    assert '--end-date "$END_DATE"' in workflow
    assert '--start-date "${{ inputs.start_date }}"' not in workflow
    assert '--end-date "${{ inputs.end_date }}"' not in workflow
    assert "start_date must use YYYY-MM-DD" in workflow
