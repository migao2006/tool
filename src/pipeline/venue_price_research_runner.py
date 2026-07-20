"""Venue-scoped artifact orchestration for shared price research models."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from datetime import date
from importlib.metadata import version
import json
from pathlib import Path

from .contracts import (
    PipelineBatch,
    PipelineContext,
    PipelineResult,
    PipelineStatus,
)
from .research_dataset import PreparedResearchDataset, ResearchDatasetError
from .twse_research_prediction_publisher import TwseResearchPredictionPublisher
from .venue_research_bundle_contract import ResearchBundlePublisher
from .venue_research_cost import (
    research_cost_metadata,
    resolve_research_cost_identity,
)
from .venue_research_profile import VenuePriceResearchProfile
from .venue_research_walk_forward import WalkForwardBlocked, evaluate_walk_forward


class VenuePriceResearchRunner:
    """Persist venue-isolated evaluation without changing ranking semantics."""

    def __init__(
        self,
        profile: VenuePriceResearchProfile,
        *,
        bundle_publisher: ResearchBundlePublisher | None = None,
    ) -> None:
        self.profile = profile
        self.bundle_publisher = bundle_publisher

    def train(self, batch: PipelineBatch, context: PipelineContext) -> PipelineResult:
        try:
            dataset = PreparedResearchDataset.from_frame(
                batch.records,
                feature_names=self.profile.feature_names,
                horizon=context.horizon,
                market=self.profile.market,
                feature_schema_hash=self.profile.feature_schema_hash,
            )
        except ResearchDatasetError:
            return self._result(
                batch,
                context,
                reason_codes=(self.profile.dataset_invalid_reason_code,),
            )
        if batch.source_hash is None:
            return self._result(
                batch,
                context,
                reason_codes=("INPUT_ARTIFACT_HASH_MISSING",),
            )
        if (
            dataset.provenance["label_version"] != self.profile.expected_label_version
            or dataset.provenance["benchmark_id"] != self.profile.expected_benchmark_id
        ):
            return self._result(
                batch,
                context,
                reason_codes=(f"{self.profile.market}_RESEARCH_PROVENANCE_MISMATCH",),
            )
        cost_identity = resolve_research_cost_identity(dataset, context)
        if cost_identity is None:
            return self._result(
                batch,
                context,
                reason_codes=("COST_PROFILE_PROVENANCE_MISMATCH",),
            )
        try:
            evaluated = evaluate_walk_forward(
                dataset,
                context,
                market=self.profile.market,
                feature_schema_hash=self.profile.feature_schema_hash,
                fold_scope_prefix=self.profile.fold_scope_prefix,
                scope=self.profile.scope,
            )
        except WalkForwardBlocked as error:
            return self._result(
                batch,
                context,
                reason_codes=(error.reason_code,),
                metrics=error.metrics,
                cost_profile_version=cost_identity.version,
            )

        metrics = evaluated.metrics
        library_versions = {
            "lightgbm": version("lightgbm"),
            "scikit-learn": version("scikit-learn"),
        }
        artifacts: dict[str, str] = {}
        if self.bundle_publisher is not None:
            bundle = self.bundle_publisher(
                batch=batch,
                context=context,
                dataset=dataset,
                fold=evaluated.last_fold,
                result=evaluated.last_fold_result,
                model_version=self.profile.model_version,
                feature_schema_hash=self.profile.feature_schema_hash,
                library_versions=library_versions,
            )
            metrics["research_model_bundle_manifest_sha256"] = (
                bundle.manifest.manifest_sha256
            )
            metrics["research_model_bundle_fold_number"] = (
                evaluated.last_fold.fold_number
            )
            artifacts.update(
                {
                    "research_model_bundle": bundle.bundle_dir.resolve().as_uri(),
                    "research_model_bundle_manifest": (
                        bundle.manifest_path.resolve().as_uri()
                    ),
                }
            )
        else:
            metrics["research_model_bundle_status"] = "NOT_EMITTED"
            metrics["research_model_bundle_reason"] = (
                self.profile.bundle_unavailable_reason_code
                or "RESEARCH_MODEL_BUNDLE_NOT_CONFIGURED"
            )

        prediction_path = self._artifact_path(batch, context, "oos-predictions", "json")
        published = TwseResearchPredictionPublisher().publish(
            prediction_path,
            fold_batches=evaluated.prediction_batches,
            horizon=context.horizon,
            model_version=self.profile.model_version,
            feature_schema_hash=self.profile.feature_schema_hash,
            input_artifact_sha256=batch.source_hash,
            provenance=dataset.provenance,
            model_metadata={
                "rank_model": "LightGBM LGBMRanker lambdarank",
                "direction_model": "LightGBM multiclass",
                "quantile_model": "LightGBM quantile 0.10/0.50/0.90",
                "random_seed": context.config.rank.seed,
                "library_versions": library_versions,
            },
            cost_metadata=research_cost_metadata(context, cost_identity),
            validation=metrics,
            reason_codes=(
                self.profile.primary_reason_code,
                "LATEST_COMPLETED_OOS_TEST_CROSS_SECTION",
                "LOCKED_HOLDOUT_NOT_EXECUTED",
                "FORMAL_DECISION_POLICY_NOT_EXECUTED",
            ),
        )
        metrics["research_prediction_snapshot_sha256"] = published.artifact_sha256
        metrics["research_prediction_as_of_date"] = (
            published.snapshot.as_of_date.isoformat()
        )
        metrics["research_prediction_count"] = len(published.snapshot.predictions)
        report_path = self._write_report(batch, context, dataset, metrics)
        artifacts.update(
            {
                "walk_forward_report": report_path.resolve().as_uri(),
                "research_prediction_snapshot": prediction_path.resolve().as_uri(),
            }
        )
        reasons = [self.profile.primary_reason_code, "LOCKED_HOLDOUT_NOT_EXECUTED"]
        if (
            self.bundle_publisher is None
            and self.profile.bundle_unavailable_reason_code
        ):
            reasons.append(self.profile.bundle_unavailable_reason_code)
        return self._result(
            batch,
            context,
            reason_codes=tuple(reasons),
            metrics=metrics,
            artifacts=artifacts,
            training_end_date=published.snapshot.training_end_date,
            cost_profile_version=cost_identity.version,
        )

    def backtest(
        self, batch: PipelineBatch, context: PipelineContext
    ) -> PipelineResult:
        return self._result(
            batch,
            context,
            reason_codes=("EXECUTION_BACKTEST_NOT_IMPLEMENTED",),
        )

    def infer(self, batch: PipelineBatch, context: PipelineContext) -> PipelineResult:
        return self._result(
            batch,
            context,
            reason_codes=("RESEARCH_MODEL_NOT_PROMOTED_FOR_INFERENCE",),
        )

    def _write_report(
        self,
        batch: PipelineBatch,
        context: PipelineContext,
        dataset: PreparedResearchDataset,
        metrics: dict[str, object],
    ) -> Path:
        target = self._artifact_path(batch, context, "price", "json")
        payload = {
            "status": "RESEARCH_ONLY",
            "market": self.profile.market,
            "horizon": context.horizon,
            "source_uri": batch.source_uri,
            "source_hash": batch.source_hash,
            "feature_schema_hash": self.profile.feature_schema_hash,
            "provenance": dataset.provenance,
            "metrics": metrics,
        }
        _ = target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return target

    def _artifact_path(
        self,
        batch: PipelineBatch,
        context: PipelineContext,
        kind: str,
        suffix: str,
    ) -> Path:
        source_hash = batch.source_hash or "unhashed"
        target = (
            context.artifact_root
            / f"horizon_{context.horizon}"
            / "research"
            / f"{self.profile.artifact_stem}-{kind}-{source_hash[:12]}.{suffix}"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def _result(
        self,
        batch: PipelineBatch,
        context: PipelineContext,
        *,
        reason_codes: tuple[str, ...],
        metrics: dict[str, object] | None = None,
        artifacts: dict[str, str] | None = None,
        training_end_date: date | None = None,
        cost_profile_version: str | None = None,
    ) -> PipelineResult:
        return PipelineResult(
            mode=context.mode,
            horizon=context.horizon,
            status=PipelineStatus.RESEARCH_ONLY,
            reason_codes=reason_codes,
            records_read=len(batch.records),
            artifacts=artifacts or {},
            metrics=metrics or {},
            source_uri=batch.source_uri,
            source_hash=batch.source_hash,
            run_id=(
                f"{self.profile.artifact_stem}-research-"
                f"{(batch.source_hash or 'unhashed')[:12]}"
            ),
            model_version=self.profile.model_version,
            feature_schema_hash=self.profile.feature_schema_hash,
            cost_profile_version=(
                cost_profile_version or context.config.cost.profile_version
            ),
            training_end_date=training_end_date,
        )


__all__ = [
    "VenuePriceResearchRunner",
]
