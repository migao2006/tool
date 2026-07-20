"""Bind verified TPEX archives to the conservative five-day assembler."""

# pyright: reportAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from datetime import datetime, timezone
from typing import final

from src.core.horizon import PRODUCTION_HORIZON
from src.data.archive.historical_parquet_reader import HistoricalParquetReader
from src.data.archive.manifest_repository import HistoricalArchiveManifestSnapshot
from src.data.research.tpex_feature_artifact_contracts import (
    VerifiedTpexFeatureArtifact,
)
from src.data.research.tpex_feature_artifact_reader import TpexFeatureArtifactReader
from src.trading.transaction_cost import TransactionCostModel

from .research_assembly_profile import TPEX_RESEARCH_ASSEMBLY_PROFILE
from .tpex_research_archive_inputs import (
    TPEX_DAILY_BAR_FILTERS,
    TPEX_OHLC_FILTERS,
    TpexResearchArchiveInputLoader,
    TpexResearchDatasetBuildError,
)
from .twse_prepared_research_contracts import (
    prepared_dataset_snapshot_hash_for_market,
)
from .twse_research_dataset_assembler import assemble_research_dataset
from .twse_research_dataset_build import ResearchDatasetBuildResult


TPEX_BENCHMARK_ID = "TPEX_PRICE_INDEX"
_CALENDAR_LIMITATION = "TRADING_CALENDAR_DERIVED_FROM_BENCHMARK_RESEARCH_ONLY"


@final
class TpexResearchDatasetBuilder:
    """Verify TPEX bytes and derive provenance before assembling labels."""

    def __init__(
        self,
        archive_reader: HistoricalParquetReader,
        *,
        feature_reader: TpexFeatureArtifactReader | None = None,
    ) -> None:
        self.archive_inputs = TpexResearchArchiveInputLoader(archive_reader)
        self.feature_reader = feature_reader or TpexFeatureArtifactReader()

    def build(
        self,
        *,
        daily_manifests: HistoricalArchiveManifestSnapshot,
        benchmark_manifests: HistoricalArchiveManifestSnapshot,
        feature_artifact: VerifiedTpexFeatureArtifact,
        horizon: int = PRODUCTION_HORIZON,
        transaction_cost_model: TransactionCostModel | None = None,
        cost_profile: str = "base_cost",
    ) -> ResearchDatasetBuildResult:
        if horizon != PRODUCTION_HORIZON:
            raise TpexResearchDatasetBuildError(
                "UNSUPPORTED_HORIZON",
                "Only the independent TPEX horizon=5 dataset is available",
            )
        feature_rows = self.feature_reader.read_table(feature_artifact).to_pandas()
        archives = self.archive_inputs.load(
            daily_manifests=daily_manifests,
            benchmark_manifests=benchmark_manifests,
            calendar_snapshot=None,
            feature_rows=feature_rows,
            expected_daily_snapshot_sha256=(
                feature_artifact.manifest.source_archive_snapshot_sha256
            ),
        )
        benchmark_version = (
            f"{archives.benchmark_source_version}@snapshot:"
            f"{archives.benchmark_snapshot_sha256}"
        )
        assembly = assemble_research_dataset(
            profile=TPEX_RESEARCH_ASSEMBLY_PROFILE,
            raw_bars=archives.raw_bars,
            feature_rows=feature_rows,
            benchmark_sessions=archives.benchmark_rows,
            benchmark_id=TPEX_BENCHMARK_ID,
            benchmark_version=benchmark_version,
            dataset_snapshot_id=(
                feature_artifact.manifest.dataset_snapshot_sha256
            ),
            source_hash=feature_artifact.manifest.parquet_sha256,
            transaction_cost_model=transaction_cost_model,
            cost_profile=cost_profile,
            corporate_action_history_verified=False,
            security_state_history_verified=False,
            feature_point_in_time_verified=False,
            extra_audit_reason_codes=(_CALENDAR_LIMITATION,),
        )
        if assembly.prepared_rows.empty:
            raise TpexResearchDatasetBuildError(
                "TPEX_RESEARCH_DATASET_EMPTY",
                "No row passed the conservative TPEX assembly gates",
            )
        prepared_snapshot = prepared_dataset_snapshot_hash_for_market(
            market="TPEX",
            feature_artifact_sha256=feature_artifact.manifest.parquet_sha256,
            daily_archive_snapshot_sha256=(
                feature_artifact.manifest.source_archive_snapshot_sha256
            ),
            current_identity_snapshot_sha256=(
                feature_artifact.manifest.current_identity_snapshot_sha256
            ),
            benchmark_archive_snapshot_sha256=(
                archives.benchmark_snapshot_sha256
            ),
            calendar_snapshot_sha256=archives.calendar_snapshot_sha256,
            feature_dataset_snapshot_id=(
                feature_artifact.manifest.dataset_snapshot_sha256
            ),
            label_version=assembly.audit.label_version,
            cost_profile_version=assembly.audit.cost_profile_version,
            horizon=horizon,
        )
        return ResearchDatasetBuildResult(
            assembly=assembly,
            daily_manifest_count=archives.daily_manifest_count,
            daily_verified_row_count=len(archives.raw_bars),
            benchmark_manifest_count=archives.benchmark_manifest_count,
            benchmark_verified_row_count=len(archives.benchmark_rows),
            daily_archive_snapshot_sha256=(
                feature_artifact.manifest.source_archive_snapshot_sha256
            ),
            current_identity_snapshot_sha256=(
                feature_artifact.manifest.current_identity_snapshot_sha256
            ),
            feature_artifact_sha256=feature_artifact.manifest.parquet_sha256,
            calendar_snapshot_sha256=archives.calendar_snapshot_sha256,
            benchmark_snapshot_sha256=archives.benchmark_snapshot_sha256,
            prepared_dataset_snapshot_sha256=prepared_snapshot,
            benchmark_version=benchmark_version,
            generated_at=datetime.now(timezone.utc),
        )


__all__ = [
    "TPEX_BENCHMARK_ID",
    "TPEX_DAILY_BAR_FILTERS",
    "TPEX_OHLC_FILTERS",
    "TpexResearchDatasetBuildError",
    "TpexResearchDatasetBuilder",
]
