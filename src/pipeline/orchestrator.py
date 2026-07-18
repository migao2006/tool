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
from .promotion import PromotionBinding, audit_promotion_manifest
from .repositories import DataSourceError
from .status_policy import enforce_configured_status_cap


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

        def finalize(result: PipelineResult) -> PipelineResult:
            return enforce_configured_status_cap(result, config.status)

        if repository is None:
            return finalize(
                self._research_only(mode, horizon, "DATA_SOURCE_NOT_CONFIGURED")
            )
        try:
            batch = repository.load(mode=mode, horizon=horizon, as_of_date=as_of_date)
        except DataSourceError:
            return finalize(self._research_only(mode, horizon, "REAL_DATA_UNAVAILABLE"))
        except Exception:
            return finalize(
                PipelineResult(
                    mode=mode,
                    horizon=horizon,
                    status=PipelineStatus.FAIL,
                    reason_codes=("DATA_SOURCE_ERROR",),
                )
            )
        audit = audit_batch(batch, mode=mode, horizon=horizon, as_of_date=as_of_date)
        if not audit.passed:
            return finalize(
                PipelineResult(
                    mode=mode,
                    horizon=horizon,
                    status=PipelineStatus.RESEARCH_ONLY,
                    reason_codes=audit.reason_codes,
                    records_read=audit.record_count,
                    source_uri=batch.source_uri,
                    source_hash=batch.source_hash,
                )
            )
        if runner is None:
            return finalize(
                PipelineResult(
                    mode=mode,
                    horizon=horizon,
                    status=PipelineStatus.RESEARCH_ONLY,
                    reason_codes=("PIPELINE_RUNNER_NOT_CONFIGURED",),
                    records_read=audit.record_count,
                    source_uri=batch.source_uri,
                    source_hash=batch.source_hash,
                )
            )
        method = getattr(runner, mode.value)
        try:
            result = method(batch, context)
        except Exception:
            return finalize(
                PipelineResult(
                    mode=mode,
                    horizon=horizon,
                    status=PipelineStatus.FAIL,
                    reason_codes=(f"{mode.value.upper()}_RUNNER_ERROR",),
                    records_read=audit.record_count,
                    source_uri=batch.source_uri,
                    source_hash=batch.source_hash,
                )
            )
        if result.mode is not mode or result.horizon != horizon:
            return finalize(
                PipelineResult(
                    mode=mode,
                    horizon=horizon,
                    status=PipelineStatus.FAIL,
                    reason_codes=("RUNNER_CONTEXT_MISMATCH",),
                    records_read=audit.record_count,
                    source_uri=batch.source_uri,
                    source_hash=batch.source_hash,
                )
            )
        if (
            result.records_read != audit.record_count
            or result.source_uri != batch.source_uri
            or result.source_hash != batch.source_hash
        ):
            return finalize(
                PipelineResult(
                    mode=mode,
                    horizon=horizon,
                    status=PipelineStatus.FAIL,
                    reason_codes=("RUNNER_PROVENANCE_MISMATCH",),
                    records_read=audit.record_count,
                    source_uri=batch.source_uri,
                    source_hash=batch.source_hash,
                )
            )
        result = finalize(result)
        if result.status is not PipelineStatus.PASS:
            return result
        if audit.latest_decision_date is None:
            return PipelineResult(
                mode=mode,
                horizon=horizon,
                status=PipelineStatus.FAIL,
                reason_codes=("AUDIT_DECISION_CUTOFF_MISSING",),
                records_read=result.records_read,
                artifacts=result.artifacts,
                metrics=result.metrics,
                source_uri=result.source_uri,
                source_hash=result.source_hash,
            )
        if (
            result.run_id is None
            or result.source_hash is None
            or result.model_version is None
            or result.feature_schema_hash is None
            or result.cost_profile_version is None
            or result.training_end_date is None
        ):
            return PipelineResult(
                mode=mode,
                horizon=horizon,
                status=PipelineStatus.FAIL,
                reason_codes=("PASS_METADATA_MISSING",),
                records_read=result.records_read,
                artifacts=result.artifacts,
                metrics=result.metrics,
                source_uri=result.source_uri,
                source_hash=result.source_hash,
            )
        promotion = audit_promotion_manifest(
            self.artifact_root,
            binding=PromotionBinding(
                horizon=horizon,
                mode=mode.value,
                run_id=result.run_id,
                source_hash=result.source_hash,
                model_version=result.model_version,
                feature_schema_hash=result.feature_schema_hash,
                cost_profile_version=result.cost_profile_version,
                training_end_date=result.training_end_date,
                effective_date=audit.latest_decision_date,
                artifact_uris=result.artifacts,
            ),
        )
        if promotion.passed:
            return result
        return PipelineResult(
            mode=mode,
            horizon=horizon,
            status=PipelineStatus.FAIL,
            reason_codes=promotion.reason_codes,
            records_read=result.records_read,
            artifacts=result.artifacts,
            metrics=result.metrics,
            source_uri=result.source_uri,
            source_hash=result.source_hash,
            run_id=result.run_id,
            model_version=result.model_version,
            feature_schema_hash=result.feature_schema_hash,
            cost_profile_version=result.cost_profile_version,
            training_end_date=result.training_end_date,
        )

    @staticmethod
    def _research_only(mode: PipelineMode, horizon: int, reason: str) -> PipelineResult:
        return PipelineResult(
            mode=mode,
            horizon=horizon,
            status=PipelineStatus.RESEARCH_ONLY,
            reason_codes=(reason,),
        )
