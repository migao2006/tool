"""Publish the mechanically last fold as an immutable research bundle."""

# pyright: reportAny=false

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path

from src.validation.purged_walk_forward import PurgedFold

from .contracts import PipelineBatch, PipelineContext
from .research_dataset import PreparedResearchDataset
from .twse_research_fold_runner import TwseFoldResearchResult
from .twse_research_model_bundle_io import (
    TwseResearchBundleWriter,
    WrittenTwseResearchBundle,
)


def publish_last_fold_bundle(
    *,
    batch: PipelineBatch,
    context: PipelineContext,
    dataset: PreparedResearchDataset,
    fold: PurgedFold,
    result: TwseFoldResearchResult,
    model_version: str,
    feature_schema_hash: str,
    library_versions: Mapping[str, str],
    research_run_provenance: Mapping[str, object] | None,
) -> WrittenTwseResearchBundle:
    """Persist the final chronological fold without metric-based selection."""

    return _publish_last_fold_bundle(
        batch=batch,
        context=context,
        dataset=dataset,
        fold=fold,
        result=result,
        model_version=model_version,
        feature_schema_hash=feature_schema_hash,
        library_versions=library_versions,
        research_run_provenance=research_run_provenance,
        market="TWSE",
        artifact_stem="twse",
        primary_reason_code="TWSE_PRICE_ONLY_RESEARCH",
    )


def publish_tpex_last_fold_bundle(
    *,
    batch: PipelineBatch,
    context: PipelineContext,
    dataset: PreparedResearchDataset,
    fold: PurgedFold,
    result: TwseFoldResearchResult,
    model_version: str,
    feature_schema_hash: str,
    library_versions: Mapping[str, str],
    research_run_provenance: Mapping[str, object] | None,
) -> WrittenTwseResearchBundle:
    """Persist only a TPEX-trained fold under a TPEX-bound manifest."""

    return _publish_last_fold_bundle(
        batch=batch,
        context=context,
        dataset=dataset,
        fold=fold,
        result=result,
        model_version=model_version,
        feature_schema_hash=feature_schema_hash,
        library_versions=library_versions,
        research_run_provenance=research_run_provenance,
        market="TPEX",
        artifact_stem="tpex",
        primary_reason_code="TPEX_PRICE_ONLY_RESEARCH",
    )


def _publish_last_fold_bundle(
    *,
    batch: PipelineBatch,
    context: PipelineContext,
    dataset: PreparedResearchDataset,
    fold: PurgedFold,
    result: TwseFoldResearchResult,
    model_version: str,
    feature_schema_hash: str,
    library_versions: Mapping[str, str],
    research_run_provenance: Mapping[str, object] | None,
    market: str,
    artifact_stem: str,
    primary_reason_code: str,
) -> WrittenTwseResearchBundle:
    """Shared implementation with exact market identity in every artifact."""

    if batch.source_hash is None:
        raise ValueError("bundle publication requires the verified input hash")
    direction_estimator = result.fitted_components.direction_model.model
    direction_classes = tuple(
        str(value) for value in getattr(direction_estimator, "classes_", ())
    )
    return TwseResearchBundleWriter().write(
        _bundle_path(batch, context, fold.fold_number, artifact_stem),
        components=result.fitted_components,
        model_version=model_version,
        horizon=context.horizon,
        fold_number=fold.fold_number,
        feature_schema_hash=feature_schema_hash,
        input_artifact_sha256=batch.source_hash,
        provenance=dataset.provenance,
        random_seed=context.config.rank.seed,
        feature_names=dataset.feature_names,
        direction_classes=direction_classes,
        training_dates=fold.train_dates,
        calibration_dates=fold.calibration_dates,
        evaluated_test_dates=fold.test_dates,
        library_versions=library_versions,
        research_run_provenance=research_run_provenance,
        reason_codes=(
            primary_reason_code,
            "MECHANICAL_LAST_WALK_FORWARD_FOLD",
            "LOCKED_HOLDOUT_NOT_EXECUTED",
            "MODEL_NOT_FORMALLY_PROMOTED",
        ),
        git_commit=(
            str(research_run_provenance["git_commit"])
            if research_run_provenance is not None
            else os.environ.get("GITHUB_SHA")
        ),
        market=market,
    )


def _bundle_path(
    batch: PipelineBatch,
    context: PipelineContext,
    fold_number: int,
    artifact_stem: str = "twse",
) -> Path:
    source_hash = batch.source_hash or "unhashed"
    return (
        context.artifact_root
        / f"horizon_{context.horizon}"
        / "research"
        / f"{artifact_stem}-model-bundle-{source_hash[:12]}-fold-{fold_number}"
    )


__all__ = ["publish_last_fold_bundle", "publish_tpex_last_fold_bundle"]
