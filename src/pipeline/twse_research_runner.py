"""Purged walk-forward trainer for the TWSE price-only research baseline."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from importlib.metadata import version
import json
from pathlib import Path
from typing import cast

from src.features.twse_price_volume_schema import (
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
)
from src.validation.purged_walk_forward import (
    PurgedWalkForwardSplitter,
    locked_holdout_split,
)

from .contracts import (
    PipelineBatch,
    PipelineContext,
    PipelineResult,
    PipelineStatus,
)
from .research_dataset import PreparedResearchDataset, ResearchDatasetError
from .research_fold_metrics import mean_scalar_metrics
from .twse_research_fold_runner import TwseFoldResearchResult, evaluate_research_fold
from .twse_research_bundle_publisher import publish_last_fold_bundle
from .twse_research_prediction_publisher import (
    FoldResearchPredictionBatch,
    TwseResearchPredictionPublisher,
)


TRADING_DAYS_PER_YEAR = 252
TRADING_DAYS_PER_MONTH = 21


class TwsePriceResearchRunner:
    """Train real prepared rows while keeping the locked holdout untouched."""

    def train(self, batch: PipelineBatch, context: PipelineContext) -> PipelineResult:
        try:
            dataset = PreparedResearchDataset.from_frame(
                batch.records,
                horizon=context.horizon,
            )
        except ResearchDatasetError:
            return self._result(
                batch,
                context,
                reason_codes=("TWSE_RESEARCH_DATASET_INVALID",),
            )
        if batch.source_hash is None:
            return self._result(
                batch,
                context,
                reason_codes=("INPUT_ARTIFACT_HASH_MISSING",),
            )
        observations = dataset.observations()
        holdout_dates = (
            context.config.validation.locked_holdout_months * TRADING_DAYS_PER_MONTH
        )
        try:
            development_indices, holdout_indices = locked_holdout_split(
                observations,
                holdout_trading_dates=holdout_dates,
                purge_trading_dates=context.config.validation.purge_trading_days,
            )
        except ValueError:
            return self._result(
                batch,
                context,
                reason_codes=("INSUFFICIENT_LOCKED_HOLDOUT_HISTORY",),
            )

        development = PreparedResearchDataset.from_frame(
            dataset.frame.iloc[list(development_indices)].copy(),
            feature_names=dataset.feature_names,
            horizon=context.horizon,
        )
        splitter = PurgedWalkForwardSplitter(
            minimum_train_dates=(
                context.config.validation.minimum_training_years * TRADING_DAYS_PER_YEAR
            ),
            calibration_dates=(
                context.config.validation.calibration_months * TRADING_DAYS_PER_MONTH
            ),
            test_dates=(context.config.validation.test_months * TRADING_DAYS_PER_MONTH),
            purge_trading_dates=context.config.validation.purge_trading_days,
            step_dates=(context.config.validation.step_months * TRADING_DAYS_PER_MONTH),
        )
        folds = tuple(splitter.split(development.observations()))
        if not folds:
            return self._result(
                batch,
                context,
                reason_codes=("INSUFFICIENT_WALK_FORWARD_HISTORY",),
                metrics={
                    "locked_holdout_executed": False,
                    "locked_holdout_rows": len(holdout_indices),
                },
            )

        reports: list[dict[str, object]] = []
        fold_prediction_batches: list[FoldResearchPredictionBatch] = []
        last_fold_result: TwseFoldResearchResult | None = None
        for position, fold in enumerate(folds):
            evaluated = evaluate_research_fold(development, fold, context)
            reports.append(evaluated.report)
            fold_prediction_batches.append(evaluated.prediction_batch)
            if position == len(folds) - 1:
                last_fold_result = evaluated
        if last_fold_result is None:
            raise RuntimeError("mechanical last walk-forward fold was not evaluated")
        last_fold = folds[-1]

        ranking_primary: list[Mapping[str, object]] = []
        for report in reports:
            ranking_section = report.get("ranking")
            if not isinstance(ranking_section, Mapping):
                raise RuntimeError("ranking fold report is invalid")
            ranking_mapping = cast(Mapping[str, object], ranking_section)
            model_section = ranking_mapping.get("model")
            if not isinstance(model_section, Mapping):
                raise RuntimeError("ranking model fold report is invalid")
            ranking_primary.append(cast(Mapping[str, object], model_section))
        metrics: dict[str, object] = {
            "system_status": "RESEARCH_ONLY",
            "scope": "TWSE_PRICE_ONLY",
            "fold_count": len(reports),
            "walk_forward": reports,
            "ranking_mean": mean_scalar_metrics(ranking_primary),
            "locked_holdout_executed": False,
            "locked_holdout_rows": len(holdout_indices),
            "locked_holdout_reason": "FROZEN_UNTIL_RESEARCH_DESIGN_IS_LOCKED",
        }
        model_version = "twse-price-research-h5-v1"
        library_versions = {
            "lightgbm": version("lightgbm"),
            "scikit-learn": version("scikit-learn"),
        }
        written_bundle = publish_last_fold_bundle(
            batch=batch,
            context=context,
            dataset=dataset,
            fold=last_fold,
            result=last_fold_result,
            model_version=model_version,
            feature_schema_hash=TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
            library_versions=library_versions,
        )
        metrics["research_model_bundle_manifest_sha256"] = (
            written_bundle.manifest.manifest_sha256
        )
        metrics["research_model_bundle_fold_number"] = last_fold.fold_number
        prediction_path = self._prediction_path(batch, context)
        published = TwseResearchPredictionPublisher().publish(
            prediction_path,
            fold_batches=fold_prediction_batches,
            horizon=context.horizon,
            model_version=model_version,
            feature_schema_hash=TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
            input_artifact_sha256=batch.source_hash,
            provenance=dataset.provenance,
            model_metadata={
                "rank_model": "LightGBM LGBMRanker lambdarank",
                "direction_model": "LightGBM multiclass",
                "quantile_model": "LightGBM quantile 0.10/0.50/0.90",
                "random_seed": context.config.rank.seed,
                "library_versions": library_versions,
            },
            cost_metadata={
                "asset_type": context.config.cost.asset_type,
                "commission_rate": context.config.cost.commission_rate,
                "commission_discount": context.config.cost.commission_discount,
                "minimum_fee": context.config.cost.minimum_fee,
                "sell_tax_rate": context.config.cost.sell_tax_rate,
                "estimated_order_notional_ntd": (
                    context.config.cost.estimated_order_notional_ntd
                ),
                "spread_model": context.config.cost.spread_model,
                "slippage_scenario": context.config.cost.slippage_scenario,
                "market_impact_parameter": (
                    context.config.cost.market_impact_parameter
                ),
                "max_adv_participation": (context.config.cost.max_adv_participation),
            },
            validation=metrics,
            reason_codes=(
                "TWSE_PRICE_ONLY_RESEARCH",
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
        return self._result(
            batch,
            context,
            reason_codes=(
                "TWSE_PRICE_ONLY_RESEARCH",
                "LOCKED_HOLDOUT_NOT_EXECUTED",
            ),
            metrics=metrics,
            artifacts={
                "walk_forward_report": report_path.resolve().as_uri(),
                "research_prediction_snapshot": prediction_path.resolve().as_uri(),
                "research_model_bundle": (
                    written_bundle.bundle_dir.resolve().as_uri()
                ),
                "research_model_bundle_manifest": (
                    written_bundle.manifest_path.resolve().as_uri()
                ),
            },
            training_end_date=published.snapshot.training_end_date,
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

    @staticmethod
    def _write_report(
        batch: PipelineBatch,
        context: PipelineContext,
        dataset: PreparedResearchDataset,
        metrics: dict[str, object],
    ) -> Path:
        source_hash = batch.source_hash or "unhashed"
        target = (
            context.artifact_root
            / f"horizon_{context.horizon}"
            / "research"
            / f"twse-price-{source_hash[:12]}.json"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": "RESEARCH_ONLY",
            "horizon": context.horizon,
            "source_uri": batch.source_uri,
            "source_hash": batch.source_hash,
            "feature_schema_hash": TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
            "provenance": dataset.provenance,
            "metrics": metrics,
        }
        _ = target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return target

    @staticmethod
    def _prediction_path(batch: PipelineBatch, context: PipelineContext) -> Path:
        source_hash = batch.source_hash or "unhashed"
        return (
            context.artifact_root
            / f"horizon_{context.horizon}"
            / "research"
            / f"twse-oos-predictions-{source_hash[:12]}.json"
        )

    @staticmethod
    def _result(
        batch: PipelineBatch,
        context: PipelineContext,
        *,
        reason_codes: tuple[str, ...],
        metrics: dict[str, object] | None = None,
        artifacts: dict[str, str] | None = None,
        training_end_date: date | None = None,
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
            run_id=f"twse-research-{(batch.source_hash or 'unhashed')[:12]}",
            model_version="twse-price-research-h5-v1",
            feature_schema_hash=TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
            cost_profile_version=context.config.cost.profile_version,
            training_end_date=training_end_date,
        )


twse_price_research_runner = TwsePriceResearchRunner()
