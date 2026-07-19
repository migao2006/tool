"""Safe adapter from a read-back verified feature artifact to research assembly."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.data.research.twse_feature_artifact_contracts import (
    VerifiedTwseFeatureArtifact,
)
from src.data.research.twse_feature_artifact_reader import TwseFeatureArtifactReader
from src.labels.direction_label import NoTradeBandConfig
from src.trading.transaction_cost import TransactionCostModel

from .twse_research_assembly_contracts import TwseResearchAssemblyResult
from .twse_research_dataset_assembler import assemble_twse_research_dataset


@dataclass(frozen=True)
class TwseFeatureArtifactAssemblyInput:
    """Rows and provenance derived from verified bytes, never caller assertions."""

    feature_rows: Any
    dataset_snapshot_id: str
    source_hash: str


def _verified_input(value: object) -> VerifiedTwseFeatureArtifact:
    if not isinstance(value, VerifiedTwseFeatureArtifact):
        raise TypeError("a verified TWSE feature artifact is required")
    return value


def feature_artifact_assembly_input(
    artifact: VerifiedTwseFeatureArtifact,
    *,
    reader: TwseFeatureArtifactReader | None = None,
) -> TwseFeatureArtifactAssemblyInput:
    """Release rows only after repeating the artifact integrity verification."""

    verified = _verified_input(artifact)
    artifact_reader = reader or TwseFeatureArtifactReader()
    table = artifact_reader.read_table(verified)
    return TwseFeatureArtifactAssemblyInput(
        # The current assembler is DataFrame based.  Conversion belongs at this
        # boundary so neither the artifact reader nor the model layer depends on
        # pandas.
        feature_rows=table.to_pandas(),
        dataset_snapshot_id=verified.manifest.dataset_snapshot_sha256,
        source_hash=verified.manifest.parquet_sha256,
    )


def assemble_from_verified_feature_artifact(
    *,
    feature_artifact: VerifiedTwseFeatureArtifact,
    raw_bars: object,
    benchmark_sessions: object,
    benchmark_id: str,
    benchmark_version: str,
    corporate_action_intervals: object | None = None,
    suspension_intervals: object | None = None,
    transaction_cost_model: TransactionCostModel | None = None,
    cost_profile: str = "base_cost",
    no_trade_band_config: NoTradeBandConfig | None = None,
    corporate_action_history_verified: bool = False,
    security_state_history_verified: bool = False,
    reader: TwseFeatureArtifactReader | None = None,
) -> TwseResearchAssemblyResult:
    """Assemble research rows with feature lineage derived from verified bytes.

    The caller can still provide separate corporate-action and market-state
    evidence, but cannot provide the feature dataset hash, file hash, or a
    point-in-time verification flag.
    """

    bound = feature_artifact_assembly_input(feature_artifact, reader=reader)
    return assemble_twse_research_dataset(
        raw_bars=raw_bars,
        feature_rows=bound.feature_rows,
        benchmark_sessions=benchmark_sessions,
        benchmark_id=benchmark_id,
        benchmark_version=benchmark_version,
        dataset_snapshot_id=bound.dataset_snapshot_id,
        source_hash=bound.source_hash,
        corporate_action_intervals=corporate_action_intervals,
        suspension_intervals=suspension_intervals,
        transaction_cost_model=transaction_cost_model,
        cost_profile=cost_profile,
        no_trade_band_config=no_trade_band_config,
        corporate_action_history_verified=corporate_action_history_verified,
        security_state_history_verified=security_state_history_verified,
        # Structural read-back is not point-in-time validation.  This adapter
        # deliberately offers no caller-controlled promotion flag.
        feature_point_in_time_verified=False,
    )


__all__ = [
    "TwseFeatureArtifactAssemblyInput",
    "assemble_from_verified_feature_artifact",
    "feature_artifact_assembly_input",
]
