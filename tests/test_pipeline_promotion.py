from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Any

import pytest

from src.pipeline.contracts import PipelineMode, PipelineResult, PipelineStatus
from src.pipeline.orchestrator import PipelineOrchestrator
from src.pipeline.promotion import (
    REQUIRED_MODEL_ARTIFACTS,
    audit_promotion_manifest,
    promotion_manifest_path,
)
from tests.pipeline_support import (
    TEST_COST_PROFILE_VERSION,
    TEST_FEATURE_SCHEMA_HASH,
    TEST_MODEL_VERSION,
    TEST_RUN_ID,
    TEST_TRAINING_END_DATE,
    RecordingRunner,
    Repository,
    frame,
    promotion_binding,
    write_config_with_status,
    write_pass_manifest,
)


def test_reviewed_pass_config_can_publish_complete_runner_result(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts"
    artifacts = write_pass_manifest(artifact_root)
    result = PipelineOrchestrator(
        config_path=write_config_with_status(tmp_path, PipelineStatus.PASS),
        artifact_root=artifact_root,
    ).run(
        mode=PipelineMode.TRAIN,
        horizon=5,
        repository=Repository(frame()),
        runner=RecordingRunner(artifacts=artifacts),
    )
    assert result.status is PipelineStatus.PASS
    assert result.reason_codes == ()


def test_pass_config_without_promotion_manifest_fails_closed(tmp_path: Path) -> None:
    result = PipelineOrchestrator(
        config_path=write_config_with_status(tmp_path, PipelineStatus.PASS),
        artifact_root=tmp_path / "missing-artifacts",
    ).run(
        mode=PipelineMode.TRAIN,
        horizon=5,
        repository=Repository(frame()),
        runner=RecordingRunner(),
    )
    assert result.status is PipelineStatus.FAIL
    assert result.reason_codes == ("PROMOTION_MANIFEST_MISSING",)


def test_promotion_manifest_requires_every_locked_acceptance_check(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "artifacts"
    artifacts = write_pass_manifest(artifact_root)
    target = promotion_manifest_path(
        artifact_root,
        horizon=5,
        mode=PipelineMode.TRAIN.value,
        run_id=TEST_RUN_ID,
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["checks"]["locked_holdout"] = "RESEARCH_ONLY"
    target.write_text(json.dumps(payload), encoding="utf-8")

    assessment = audit_promotion_manifest(
        artifact_root,
        binding=promotion_binding(artifacts),
    )
    assert not assessment.passed
    assert assessment.reason_codes == ("PROMOTION_CHECK_NOT_PASS:locked_holdout",)


def test_promotion_manifest_hashes_actual_artifact_files(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifacts = write_pass_manifest(artifact_root)
    Path(artifacts["rank_model"]).write_bytes(b"tampered")

    assessment = audit_promotion_manifest(
        artifact_root,
        binding=promotion_binding(artifacts),
    )
    assert not assessment.passed
    assert "PROMOTION_ARTIFACT_HASH_MISMATCH:rank_model" in assessment.reason_codes


def test_promotion_manifest_is_bound_to_this_source_and_mode(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifacts = write_pass_manifest(artifact_root, mode=PipelineMode.INFER)
    assessment = audit_promotion_manifest(
        artifact_root,
        binding=promotion_binding(
            artifacts,
            mode=PipelineMode.INFER,
            source_hash="different-source",
        ),
    )
    assert not assessment.passed
    assert assessment.reason_codes == ("PROMOTION_IDENTITY_MISMATCH:source_hash",)


def test_promotion_rejects_training_date_after_effective_date(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    future_training_end = date(2026, 7, 19)
    artifacts = write_pass_manifest(
        artifact_root,
        training_end_date=future_training_end,
    )
    assessment = audit_promotion_manifest(
        artifact_root,
        binding=promotion_binding(
            artifacts,
            training_end_date=future_training_end,
            effective_date=date(2026, 7, 18),
        ),
    )
    assert not assessment.passed
    assert assessment.reason_codes == ("PROMOTION_TRAINING_END_DATE_IN_FUTURE",)


def test_pipeline_uses_dataset_decision_cutoff_for_promotion(tmp_path: Path) -> None:
    training_end_date = date(2026, 7, 18)
    artifact_root = tmp_path / "artifacts"
    artifacts = write_pass_manifest(
        artifact_root,
        training_end_date=training_end_date,
    )
    result = PipelineOrchestrator(
        config_path=write_config_with_status(tmp_path, PipelineStatus.PASS),
        artifact_root=artifact_root,
    ).run(
        mode=PipelineMode.TRAIN,
        horizon=5,
        repository=Repository(frame()),
        runner=RecordingRunner(
            artifacts=artifacts,
            training_end_date=training_end_date,
        ),
    )
    assert result.status is PipelineStatus.FAIL
    assert result.reason_codes == ("PROMOTION_TRAINING_END_DATE_IN_FUTURE",)


def test_promotion_artifact_read_error_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "artifacts"
    artifacts = write_pass_manifest(artifact_root)

    def unreadable(_path: Path) -> str:
        raise OSError("test-only unreadable artifact")

    monkeypatch.setattr("src.pipeline.promotion._sha256", unreadable)
    assessment = audit_promotion_manifest(
        artifact_root,
        binding=promotion_binding(artifacts),
    )
    assert not assessment.passed
    assert "PROMOTION_ARTIFACT_READ_ERROR:rank_model" in assessment.reason_codes


@pytest.mark.parametrize(
    "overrides",
    [
        {"records_read": 0},
        {"source_uri": None},
        {"source_hash": None},
        {"run_id": None},
        {"model_version": None},
        {"feature_schema_hash": None},
        {"cost_profile_version": None},
        {"training_end_date": None},
        {"artifacts": {}},
        {"metrics": {}},
    ],
)
def test_pass_result_requires_auditable_evidence(overrides: dict[str, Any]) -> None:
    values: dict[str, Any] = {
        "mode": PipelineMode.TRAIN,
        "horizon": 5,
        "status": PipelineStatus.PASS,
        "records_read": 1,
        "artifacts": {name: f"memory://{name}" for name in REQUIRED_MODEL_ARTIFACTS},
        "metrics": {"validation_status": "PASS"},
        "source_uri": "memory://rows",
        "source_hash": "abc123",
        "run_id": TEST_RUN_ID,
        "model_version": TEST_MODEL_VERSION,
        "feature_schema_hash": TEST_FEATURE_SCHEMA_HASH,
        "cost_profile_version": TEST_COST_PROFILE_VERSION,
        "training_end_date": TEST_TRAINING_END_DATE,
    }
    values.update(overrides)
    with pytest.raises(ValueError):
        PipelineResult(**values)
