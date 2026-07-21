"""Structural boundary for optional venue-specific model bundles."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from src.validation.purged_walk_forward import PurgedFold

from .contracts import PipelineBatch, PipelineContext
from .research_dataset import PreparedResearchDataset
from .twse_research_fold_runner import TwseFoldResearchResult


class _BundleManifest(Protocol):
    @property
    def manifest_sha256(self) -> str: ...


class WrittenResearchBundle(Protocol):
    @property
    def manifest(self) -> _BundleManifest: ...

    @property
    def bundle_dir(self) -> Path: ...

    @property
    def manifest_path(self) -> Path: ...


class ResearchBundlePublisher(Protocol):
    def __call__(
        self,
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
    ) -> WrittenResearchBundle: ...


__all__ = ["ResearchBundlePublisher", "WrittenResearchBundle"]
