"""Contracts for conservative venue-scoped research-dataset assembly."""

# pyright: reportExplicitAny=false

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class ResearchRowExclusion:
    """One decision row rejected before it can reach research training."""

    symbol: str
    decision_date: date
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("exclusion symbol is required")
        if not self.reason_codes or any(not code for code in self.reason_codes):
            raise ValueError("exclusions require non-empty reason codes")


@dataclass(frozen=True)
class ResearchAssemblyAudit:
    """Aggregate evidence that explains exactly what the assembler released."""

    input_feature_row_count: int
    prepared_row_count: int
    excluded_row_count: int
    reason_counts: Mapping[str, int]
    audit_reason_codes: tuple[str, ...]
    corporate_action_history_verified: bool
    security_state_history_verified: bool
    feature_point_in_time_verified: bool
    scheduling_hint_row_count: int
    feature_schema_hash: str
    label_version: str
    benchmark_id: str
    benchmark_version: str
    cost_profile_version: str
    dataset_snapshot_id: str
    source_hash: str
    horizon: int = 5
    market: str = "TWSE"
    price_basis: str = "UNADJUSTED_RAW_OHLC"
    usage_scope: str = "MODEL_RESEARCH_ONLY"
    system_status: str = "RESEARCH_ONLY"

    def __post_init__(self) -> None:
        counts = (
            self.input_feature_row_count,
            self.prepared_row_count,
            self.excluded_row_count,
        )
        if any(value < 0 for value in (*counts, self.scheduling_hint_row_count)):
            raise ValueError("assembly counts cannot be negative")
        if (
            self.prepared_row_count + self.excluded_row_count
            != self.input_feature_row_count
        ):
            raise ValueError(
                "prepared and excluded counts must cover every feature row"
            )
        if self.horizon != 5 or self.market not in {"TWSE", "TPEX"}:
            raise ValueError("this assembler supports only TWSE/TPEX horizon=5")
        if self.usage_scope != "MODEL_RESEARCH_ONLY":
            raise ValueError("assembled rows cannot be marked production eligible")
        if self.system_status != "RESEARCH_ONLY":
            raise ValueError("assembled rows cannot be promoted by this step")
        if not self.audit_reason_codes:
            raise ValueError("research-only assembly requires audit reasons")
        trace_fields = (
            self.feature_schema_hash,
            self.label_version,
            self.benchmark_id,
            self.benchmark_version,
            self.cost_profile_version,
            self.dataset_snapshot_id,
            self.source_hash,
        )
        if any(not value.strip() for value in trace_fields):
            raise ValueError("research assembly provenance fields are required")
        if any(count < 0 for count in self.reason_counts.values()):
            raise ValueError("reason counts cannot be negative")


@dataclass(frozen=True)
class ResearchAssemblyResult:
    """Prepared pandas rows, fail-closed exclusions, and immutable audit summary."""

    prepared_rows: Any
    exclusions: tuple[ResearchRowExclusion, ...]
    audit: ResearchAssemblyAudit


# Backward-compatible public name used by the existing TWSE pipeline.
TwseResearchAssemblyResult = ResearchAssemblyResult


__all__ = [
    "ResearchAssemblyAudit",
    "ResearchAssemblyResult",
    "ResearchRowExclusion",
    "TwseResearchAssemblyResult",
]
