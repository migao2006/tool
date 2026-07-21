from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.pipeline.contracts import (
    PipelineBatch,
    PipelineContext,
    PipelineMode,
    PipelineResult,
    PipelineStatus,
)
from src.pipeline.orchestrator import PipelineOrchestrator
from src.pipeline.twse_prepared_research_repository import (
    PreparedResearchArtifactSourceError,
)
from tests.pipeline_support import (
    CONFIG,
    RecordingRunner,
    Repository,
    frame,
    write_config_with_status,
)


def test_pipeline_requires_real_data_source() -> None:
    result = PipelineOrchestrator(config_path=CONFIG).run(
        mode=PipelineMode.TRAIN,
        horizon=5,
        repository=None,
        runner=RecordingRunner(),
    )
    assert result.status is PipelineStatus.RESEARCH_ONLY
    assert result.reason_codes == ("DATA_SOURCE_NOT_CONFIGURED",)
    assert result.metrics == {}
    assert result.artifacts == {}


def test_pipeline_preserves_stable_artifact_source_reason_code() -> None:
    class InvalidPreparedArtifactRepository:
        def load(self, **_: object) -> PipelineBatch:
            raise PreparedResearchArtifactSourceError(
                "PREPARED_RESEARCH_ARTIFACT_AUDIT_INVALID",
                "invalid prepared artifact audit",
            )

    result = PipelineOrchestrator(config_path=CONFIG).run(
        mode=PipelineMode.TRAIN,
        horizon=5,
        repository=InvalidPreparedArtifactRepository(),
        runner=RecordingRunner(),
    )

    assert result.status is PipelineStatus.RESEARCH_ONLY
    assert result.reason_codes == ("PREPARED_RESEARCH_ARTIFACT_AUDIT_INVALID",)


def test_pipeline_rejects_point_in_time_violation_before_runner() -> None:
    runner = RecordingRunner()
    result = PipelineOrchestrator(config_path=CONFIG).run(
        mode=PipelineMode.TRAIN,
        horizon=5,
        repository=Repository(frame(late=True)),
        runner=runner,
    )
    assert result.status is PipelineStatus.RESEARCH_ONLY
    assert "POINT_IN_TIME_VIOLATION" in result.reason_codes
    assert runner.calls == []


@pytest.mark.parametrize("mode", list(PipelineMode))
def test_each_mode_delegates_audited_real_rows(mode: PipelineMode) -> None:
    runner = RecordingRunner()
    result = PipelineOrchestrator(config_path=CONFIG).run(
        mode=mode,
        horizon=5,
        repository=Repository(frame()),
        runner=runner,
        as_of_date=date(2026, 7, 17) if mode is PipelineMode.INFER else None,
    )
    assert result.status is PipelineStatus.RESEARCH_ONLY
    assert result.reason_codes == ("CONFIG_STATUS_RESEARCH_ONLY",)
    assert result.records_read == 1
    assert runner.calls == [mode]


def test_research_config_never_softens_runner_failure() -> None:
    result = PipelineOrchestrator(config_path=CONFIG).run(
        mode=PipelineMode.TRAIN,
        horizon=5,
        repository=Repository(frame()),
        runner=RecordingRunner(status=PipelineStatus.FAIL),
    )
    assert result.status is PipelineStatus.FAIL
    assert result.reason_codes == ("RUNNER_RESEARCH_RESULT",)


def test_fail_config_downgrades_complete_runner_result(tmp_path: Path) -> None:
    result = PipelineOrchestrator(
        config_path=write_config_with_status(tmp_path, PipelineStatus.FAIL)
    ).run(
        mode=PipelineMode.TRAIN,
        horizon=5,
        repository=Repository(frame()),
        runner=RecordingRunner(),
    )
    assert result.status is PipelineStatus.FAIL
    assert result.reason_codes == ("CONFIG_STATUS_FAIL",)


def test_fail_config_applies_to_early_research_result(tmp_path: Path) -> None:
    result = PipelineOrchestrator(
        config_path=write_config_with_status(tmp_path, PipelineStatus.FAIL)
    ).run(
        mode=PipelineMode.TRAIN,
        horizon=5,
        repository=None,
        runner=RecordingRunner(),
    )
    assert result.status is PipelineStatus.FAIL
    assert result.reason_codes == ("CONFIG_STATUS_FAIL", "DATA_SOURCE_NOT_CONFIGURED")


@pytest.mark.parametrize(
    "runner",
    [
        RecordingRunner(source_uri="memory://wrong-source"),
        RecordingRunner(source_hash="wrong-hash"),
        RecordingRunner(records_read=2),
    ],
)
def test_runner_provenance_mismatch_fails_closed(runner: RecordingRunner) -> None:
    result = PipelineOrchestrator(config_path=CONFIG).run(
        mode=PipelineMode.TRAIN,
        horizon=5,
        repository=Repository(frame()),
        runner=runner,
    )
    assert result.status is PipelineStatus.FAIL
    assert result.reason_codes == ("RUNNER_PROVENANCE_MISMATCH",)


def test_runner_context_mismatch_fails_closed() -> None:
    class WrongContextRunner(RecordingRunner):
        def train(
            self,
            batch: PipelineBatch,
            context: PipelineContext,
        ) -> PipelineResult:
            return self._result(PipelineMode.BACKTEST, batch, context.horizon)

    result = PipelineOrchestrator(config_path=CONFIG).run(
        mode=PipelineMode.TRAIN,
        horizon=5,
        repository=Repository(frame()),
        runner=WrongContextRunner(),
    )
    assert result.status is PipelineStatus.FAIL
    assert result.reason_codes == ("RUNNER_CONTEXT_MISMATCH",)


def test_unreleased_horizon_is_blocked_in_production_pipeline() -> None:
    with pytest.raises(NotImplementedError):
        PipelineOrchestrator(config_path=CONFIG).run(
            mode=PipelineMode.TRAIN,
            horizon=3,
            repository=Repository(frame()),
            runner=RecordingRunner(),
        )


def test_pipeline_batch_requires_timezone_aware_provenance_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        PipelineBatch(frame(), "memory://rows", loaded_at=datetime(2026, 7, 17))

    batch = PipelineBatch(
        frame(),
        "memory://rows",
        loaded_at=datetime(2026, 7, 17, tzinfo=timezone.utc),
    )
    assert batch.source_uri == "memory://rows"
