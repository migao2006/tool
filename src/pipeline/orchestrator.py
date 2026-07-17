"""Small coordinator that keeps I/O, auditing, and model code separate."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.config.loader import DEFAULT_CONFIG_PATH, load_mvp_config
from src.core.horizon import require_production_horizon

from .audit import audit_batch
from .contracts import (
    DatasetRepository,
    PipelineContext,
    PipelineMode,
    PipelineResult,
    PipelineRunner,
    PipelineStatus,
)
from .repositories import DataSourceError


class PipelineOrchestrator:
    def __init__(
        self,
        *,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
        artifact_root: str | Path = "artifacts",
    ) -> None:
        self.config_path = Path(config_path)
        self.artifact_root = Path(artifact_root)

    def run(
        self,
        *,
        mode: PipelineMode,
        horizon: int,
        repository: DatasetRepository | None,
        runner: PipelineRunner | None,
        as_of_date: date | None = None,
    ) -> PipelineResult:
        require_production_horizon(horizon)
        config = load_mvp_config(self.config_path)
        context = PipelineContext(
            mode=mode,
            horizon=horizon,
            config=config,
            artifact_root=self.artifact_root,
            as_of_date=as_of_date,
        )
        if repository is None:
            return self._research_only(mode, horizon, "DATA_SOURCE_NOT_CONFIGURED")
        try:
            batch = repository.load(mode=mode, horizon=horizon, as_of_date=as_of_date)
        except DataSourceError:
            return self._research_only(mode, horizon, "REAL_DATA_UNAVAILABLE")
        except Exception:
            return PipelineResult(
                mode=mode,
                horizon=horizon,
                status=PipelineStatus.FAIL,
                reason_codes=("DATA_SOURCE_ERROR",),
            )
        audit = audit_batch(batch, mode=mode, horizon=horizon, as_of_date=as_of_date)
        if not audit.passed:
            return PipelineResult(
                mode=mode,
                horizon=horizon,
                status=PipelineStatus.RESEARCH_ONLY,
                reason_codes=audit.reason_codes,
                records_read=audit.record_count,
                source_uri=batch.source_uri,
                source_hash=batch.source_hash,
            )
        if runner is None:
            return PipelineResult(
                mode=mode,
                horizon=horizon,
                status=PipelineStatus.RESEARCH_ONLY,
                reason_codes=("PIPELINE_RUNNER_NOT_CONFIGURED",),
                records_read=audit.record_count,
                source_uri=batch.source_uri,
                source_hash=batch.source_hash,
            )
        method = getattr(runner, mode.value)
        try:
            result = method(batch, context)
        except Exception:
            return PipelineResult(
                mode=mode,
                horizon=horizon,
                status=PipelineStatus.FAIL,
                reason_codes=(f"{mode.value.upper()}_RUNNER_ERROR",),
                records_read=audit.record_count,
                source_uri=batch.source_uri,
                source_hash=batch.source_hash,
            )
        if result.mode is not mode or result.horizon != horizon:
            raise ValueError("runner result does not match pipeline context")
        return result

    @staticmethod
    def _research_only(mode: PipelineMode, horizon: int, reason: str) -> PipelineResult:
        return PipelineResult(
            mode=mode,
            horizon=horizon,
            status=PipelineStatus.RESEARCH_ONLY,
            reason_codes=(reason,),
        )
