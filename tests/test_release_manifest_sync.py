from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "release-manifest.json"
MODEL_CARD = ROOT / "model_card.json"
MODEL_CARD_MD = ROOT / "model_card.md"
CURRENT_STATUS = ROOT / "docs/current-status.md"
DIGEST = ROOT / "release-manifest.sha256"
SYNC_SCRIPT = ROOT / "scripts/sync_release_manifest.py"


def load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_generated_release_documents_are_in_sync() -> None:
    result = subprocess.run(
        [sys.executable, str(SYNC_SCRIPT), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_model_card_is_generated_from_the_single_release_manifest() -> None:
    manifest = load(MANIFEST)
    model_card = load(MODEL_CARD)

    assert model_card == manifest["model_card"]
    snapshot = model_card["published_research_snapshot"]
    assert snapshot["workflow_run_id"] == 29701335309
    assert snapshot["prediction_run_id"] == 4
    assert snapshot["git_commit"] is None
    assert (
        snapshot["git_commit_evidence_status"]
        == "NOT_RECORDED_IN_AVAILABLE_EVIDENCE"
    )
    assert snapshot["decision_gate_count"] == 8_544
    assert snapshot["decision_gates_per_prediction"] == 8
    assert snapshot["prediction_count"] == 1_068
    assert snapshot["no_trade_count"] == 1_068


def test_release_manifest_records_repository_and_remote_evidence_separately() -> None:
    manifest = load(MANIFEST)
    repository = manifest["repository_state"]
    migration_files = list((ROOT / "supabase/migrations").glob("*.sql"))

    assert repository["migration_file_count"] == len(migration_files)
    assert repository["migration_file_count"] == 36
    assert repository["patch_added_migrations"] == [
        "20260720170000_prediction_snapshot_rate_limit.sql",
        "20260720190000_prediction_snapshot_read_rpc.sql",
    ]
    assert repository["patch_requires_staging_validation"] == [
        "20260720170000_prediction_snapshot_rate_limit.sql",
        "20260720190000_prediction_snapshot_read_rpc.sql",
    ]
    assert repository["migrations_after_recorded_remote_latest"] == [
        "20260720051630_tpex_price_index_ohlc_queue.sql",
        "20260720061143_scope_prediction_runs_by_market.sql",
        "20260720064801_exclude_legacy_prediction_publisher_from_lint.sql",
        "20260720170000_prediction_snapshot_rate_limit.sql",
        "20260720190000_prediction_snapshot_read_rpc.sql",
    ]
    for environment in ("staging", "production"):
        state = repository["environment_migration_history"][environment]
        assert state["recorded_applied_count"] == 31
        assert state["evidence_status"] == "DOCUMENTED_NOT_REVERIFIED_BY_THIS_PATCH"


def test_generated_markdown_discloses_unknown_commit_and_has_no_old_snapshot() -> None:
    combined = MODEL_CARD_MD.read_text(encoding="utf-8") + CURRENT_STATUS.read_text(
        encoding="utf-8"
    )

    assert "release-manifest:model-header:start" in combined
    assert "release-manifest:model-snapshot:start" in combined
    assert "release-manifest:status-header:start" in combined
    assert "release-manifest:status-snapshot:start" in combined
    assert "未記錄於目前可用證據" in combined
    assert "29695406502" not in combined
    assert "b588f93a9d43639b7329155aafff3f3d31c00dd6e78875618e426f8dd8f50156" not in combined
    assert "0b1f116e64ccdfb3880acd352b95913e03fb8419c24196f6f4d6b2e1458b088a" not in combined


def test_manifest_digest_matches_exact_file_bytes() -> None:
    expected = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    assert DIGEST.read_text(encoding="utf-8") == (
        f"{expected}  release-manifest.json\n"
    )
