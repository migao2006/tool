"""Bind verified TWSE archives to the conservative research assembler."""

# pyright: reportAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import final

from src.core.horizon import PRODUCTION_HORIZON
from src.data.archive.historical_parquet_reader import HistoricalParquetReader
from src.data.archive.manifest_repository import HistoricalArchiveManifestSnapshot
from src.data.research.twse_feature_artifact_contracts import (
    VerifiedTwseFeatureArtifact,
)
from src.data.research.twse_feature_artifact_reader import TwseFeatureArtifactReader
from src.data.research.twse_trading_calendar_snapshot import (
    TwseTradingCalendarSnapshot,
)
from src.trading.transaction_cost import TransactionCostModel

from .twse_feature_artifact_input import feature_artifact_assembly_input
from .twse_prepared_research_contracts import (
    prepared_dataset_snapshot_hash,
    prepared_dataset_snapshot_hash_for_market,
)
from .twse_research_archive_inputs import (
    DAILY_BAR_FILTERS,
    TAIEX_OHLC_FILTERS,
    TwseResearchArchiveInputLoader,
    TwseResearchDatasetBuildError,
)
from .twse_research_assembly_contracts import TwseResearchAssemblyResult
from .twse_research_dataset_assembler import assemble_twse_research_dataset


BENCHMARK_ID = "TWSE_TAIEX_PRICE_INDEX"


@dataclass(frozen=True)
class TwseResearchDatasetBuildResult:
    """One research assembly plus auditable input counts and versions."""

    assembly: TwseResearchAssemblyResult
    daily_manifest_count: int
    daily_verified_row_count: int
    benchmark_manifest_count: int
    benchmark_verified_row_count: int
    daily_archive_snapshot_sha256: str
    current_identity_snapshot_sha256: str
    feature_artifact_sha256: str
    calendar_snapshot_sha256: str
    benchmark_snapshot_sha256: str
    prepared_dataset_snapshot_sha256: str
    benchmark_version: str
    generated_at: datetime

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        counts = (
            self.daily_manifest_count,
            self.daily_verified_row_count,
            self.benchmark_manifest_count,
            self.benchmark_verified_row_count,
        )
        if any(value <= 0 for value in counts):
            raise ValueError("verified research inputs must be non-empty")
        hashes = (
            self.daily_archive_snapshot_sha256,
            self.current_identity_snapshot_sha256,
            self.feature_artifact_sha256,
            self.calendar_snapshot_sha256,
            self.benchmark_snapshot_sha256,
            self.prepared_dataset_snapshot_sha256,
        )
        if any(len(value) != 64 for value in hashes):
            raise ValueError("research input snapshot SHA-256 is invalid")
        audit = self.assembly.audit
        expected = prepared_dataset_snapshot_hash_for_market(
            market=audit.market,
            feature_artifact_sha256=self.feature_artifact_sha256,
            daily_archive_snapshot_sha256=self.daily_archive_snapshot_sha256,
            current_identity_snapshot_sha256=self.current_identity_snapshot_sha256,
            benchmark_archive_snapshot_sha256=self.benchmark_snapshot_sha256,
            calendar_snapshot_sha256=self.calendar_snapshot_sha256,
            feature_dataset_snapshot_id=audit.dataset_snapshot_id,
            label_version=audit.label_version,
            cost_profile_version=audit.cost_profile_version,
            horizon=audit.horizon,
        )
        if expected != self.prepared_dataset_snapshot_sha256:
            raise ValueError("prepared dataset snapshot is inconsistent")

    def audit_payload(self) -> dict[str, object]:
        audit = self.assembly.audit
        return {
            "generated_at": self.generated_at.isoformat(),
            "build_status": "COMPLETED_RESEARCH_ONLY",
            "system_status": "RESEARCH_ONLY",
            "usage_scope": "MODEL_RESEARCH_ONLY",
            "horizon": audit.horizon,
            "market": audit.market,
            "input_feature_row_count": audit.input_feature_row_count,
            "prepared_row_count": audit.prepared_row_count,
            "excluded_row_count": audit.excluded_row_count,
            "exclusion_reason_counts": dict(audit.reason_counts),
            "reason_codes": list(audit.audit_reason_codes),
            "daily_manifest_count": self.daily_manifest_count,
            "daily_verified_row_count": self.daily_verified_row_count,
            "benchmark_manifest_count": self.benchmark_manifest_count,
            "benchmark_verified_row_count": self.benchmark_verified_row_count,
            "daily_archive_snapshot_sha256": self.daily_archive_snapshot_sha256,
            "current_identity_snapshot_sha256": self.current_identity_snapshot_sha256,
            "feature_artifact_sha256": self.feature_artifact_sha256,
            "calendar_snapshot_sha256": self.calendar_snapshot_sha256,
            "benchmark_snapshot_sha256": self.benchmark_snapshot_sha256,
            "prepared_dataset_snapshot_sha256": (
                self.prepared_dataset_snapshot_sha256
            ),
            "benchmark_id": audit.benchmark_id,
            "benchmark_version": self.benchmark_version,
            "benchmark_path": "T_PLUS_ONE_OPEN_TO_H_CLOSE",
            "benchmark_semantics": "PRICE_INDEX_NOT_TOTAL_RETURN",
            "dataset_snapshot_id": audit.dataset_snapshot_id,
            "source_hash": audit.source_hash,
            "feature_schema_hash": audit.feature_schema_hash,
            "label_version": audit.label_version,
            "cost_profile_version": audit.cost_profile_version,
            "corporate_action_history_verified": False,
            "security_state_history_verified": False,
            "feature_point_in_time_verified": False,
        }


ResearchDatasetBuildResult = TwseResearchDatasetBuildResult


@final
class TwseResearchDatasetBuilder:
    """Verify every byte and derive all provenance before assembling labels."""

    def __init__(
        self,
        archive_reader: HistoricalParquetReader,
        *,
        feature_reader: TwseFeatureArtifactReader | None = None,
    ) -> None:
        self.archive_inputs = TwseResearchArchiveInputLoader(archive_reader)
        self.feature_reader = feature_reader or TwseFeatureArtifactReader()

    def build(
        self,
        *,
        daily_manifests: HistoricalArchiveManifestSnapshot,
        benchmark_manifests: HistoricalArchiveManifestSnapshot,
        calendar_snapshot: TwseTradingCalendarSnapshot | None,
        feature_artifact: VerifiedTwseFeatureArtifact,
        horizon: int = PRODUCTION_HORIZON,
        transaction_cost_model: TransactionCostModel | None = None,
        cost_profile: str = "base_cost",
    ) -> TwseResearchDatasetBuildResult:
        if horizon != PRODUCTION_HORIZON:
            raise TwseResearchDatasetBuildError(
                "UNSUPPORTED_HORIZON",
                "Only the independent horizon=5 research dataset is available",
            )
        bound = feature_artifact_assembly_input(
            feature_artifact,
            reader=self.feature_reader,
        )
        archives = self.archive_inputs.load(
            daily_manifests=daily_manifests,
            benchmark_manifests=benchmark_manifests,
            calendar_snapshot=calendar_snapshot,
            feature_rows=bound.feature_rows,
            expected_daily_snapshot_sha256=(
                feature_artifact.manifest.source_archive_snapshot_sha256
            ),
        )
        benchmark_version = (
            f"{archives.benchmark_source_version}@snapshot:"
            f"{archives.benchmark_snapshot_sha256}"
        )
        assembly = assemble_twse_research_dataset(
            raw_bars=archives.raw_bars,
            feature_rows=bound.feature_rows,
            benchmark_sessions=archives.benchmark_rows,
            benchmark_id=BENCHMARK_ID,
            benchmark_version=benchmark_version,
            dataset_snapshot_id=bound.dataset_snapshot_id,
            source_hash=bound.source_hash,
            transaction_cost_model=transaction_cost_model,
            cost_profile=cost_profile,
            corporate_action_history_verified=False,
            security_state_history_verified=False,
            feature_point_in_time_verified=False,
        )
        if assembly.prepared_rows.empty:
            raise TwseResearchDatasetBuildError(
                "TWSE_RESEARCH_DATASET_EMPTY",
                "No row passed the conservative research assembly gates",
            )
        prepared_snapshot = prepared_dataset_snapshot_hash(
            feature_artifact_sha256=feature_artifact.manifest.parquet_sha256,
            daily_archive_snapshot_sha256=(
                feature_artifact.manifest.source_archive_snapshot_sha256
            ),
            current_identity_snapshot_sha256=(
                feature_artifact.manifest.current_identity_snapshot_sha256
            ),
            taiex_archive_snapshot_sha256=archives.benchmark_snapshot_sha256,
            calendar_snapshot_sha256=archives.calendar_snapshot_sha256,
            feature_dataset_snapshot_id=bound.dataset_snapshot_id,
            label_version=assembly.audit.label_version,
            cost_profile_version=assembly.audit.cost_profile_version,
            horizon=horizon,
        )
        return TwseResearchDatasetBuildResult(
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
    "BENCHMARK_ID",
    "DAILY_BAR_FILTERS",
    "TAIEX_OHLC_FILTERS",
    "TwseResearchDatasetBuildError",
    "TwseResearchDatasetBuildResult",
    "TwseResearchDatasetBuilder",
    "ResearchDatasetBuildResult",
]
