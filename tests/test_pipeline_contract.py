from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.pipeline.contracts import (
    PipelineBatch,
    PipelineMode,
    PipelineResult,
    PipelineStatus,
)
from src.pipeline.orchestrator import PipelineOrchestrator


CONFIG = Path(__file__).parents[1] / "config" / "five_day_mvp.toml"


def _frame(*, late: bool = False) -> pd.DataFrame:
    decision = "2026-07-17T06:00:00Z"
    available = "2026-07-17T07:00:00Z" if late else "2026-07-17T05:59:00Z"
    return pd.DataFrame(
        {
            "symbol": ["2330"],
            "horizon": [5],
            "decision_at": [decision],
            "available_at": [available],
        }
    )


class Repository:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def load(self, *, mode: PipelineMode, horizon: int, as_of_date: date | None) -> PipelineBatch:
        del mode, horizon, as_of_date
        return PipelineBatch(self.frame, "memory://real-test-fixture", "abc123")


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[PipelineMode] = []

    def _result(self, mode: PipelineMode, batch: PipelineBatch, horizon: int) -> PipelineResult:
        self.calls.append(mode)
        return PipelineResult(
            mode=mode,
            horizon=horizon,
            status=PipelineStatus.PASS,
            records_read=len(batch.records),
            source_uri=batch.source_uri,
            source_hash=batch.source_hash,
        )

    def train(self, batch: PipelineBatch, context) -> PipelineResult:
        return self._result(PipelineMode.TRAIN, batch, context.horizon)

    def backtest(self, batch: PipelineBatch, context) -> PipelineResult:
        return self._result(PipelineMode.BACKTEST, batch, context.horizon)

    def infer(self, batch: PipelineBatch, context) -> PipelineResult:
        return self._result(PipelineMode.INFER, batch, context.horizon)


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


def test_pipeline_rejects_point_in_time_violation_before_runner() -> None:
    runner = RecordingRunner()
    result = PipelineOrchestrator(config_path=CONFIG).run(
        mode=PipelineMode.TRAIN,
        horizon=5,
        repository=Repository(_frame(late=True)),
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
        repository=Repository(_frame()),
        runner=runner,
        as_of_date=date(2026, 7, 17) if mode is PipelineMode.INFER else None,
    )
    assert result.status is PipelineStatus.PASS
    assert result.records_read == 1
    assert runner.calls == [mode]


def test_unreleased_horizon_is_blocked_in_production_pipeline() -> None:
    with pytest.raises(NotImplementedError):
        PipelineOrchestrator(config_path=CONFIG).run(
            mode=PipelineMode.TRAIN,
            horizon=3,
            repository=Repository(_frame()),
            runner=RecordingRunner(),
        )


def test_pipeline_batch_requires_timezone_aware_provenance_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        PipelineBatch(_frame(), "memory://rows", loaded_at=datetime(2026, 7, 17))

    batch = PipelineBatch(
        _frame(),
        "memory://rows",
        loaded_at=datetime(2026, 7, 17, tzinfo=timezone.utc),
    )
    assert batch.source_uri == "memory://rows"
