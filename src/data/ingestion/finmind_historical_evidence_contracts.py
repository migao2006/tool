"""Contracts for conservative FinMind historical action/state evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class HistoricalEvidenceIdentity:
    """One verified point-in-time TWSE common-stock listing period."""

    listing_evidence_id: int
    listing_period_id: str
    security_id: int
    source_symbol: str
    effective_from: date
    effective_to: date | None
    available_at: datetime
    market: str = "TWSE"
    asset_type: str = "COMMON_STOCK"

    def __post_init__(self) -> None:
        for value in (
            self.listing_evidence_id,
            self.security_id,
        ):
            if isinstance(value, bool) or value <= 0:
                raise ValueError("identity database IDs must be positive integers")
        if not self.listing_period_id.strip() or not self.source_symbol.strip():
            raise ValueError("listing period and source symbol are required")
        if self.market != "TWSE" or self.asset_type != "COMMON_STOCK":
            raise ValueError("historical evidence identity must be TWSE common stock")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("identity effective_to must be after effective_from")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("identity available_at must be timezone-aware")

    def covers(self, event_date: date, observed_at: datetime) -> bool:
        return (
            self.effective_from <= event_date
            and (self.effective_to is None or event_date < self.effective_to)
            and self.available_at <= observed_at
        )


@dataclass(frozen=True)
class NormalizedFinMindHistoricalEvidence:
    """Canonical rows plus exclusions; no training-readiness claim is implied."""

    action_rows: tuple[dict[str, object], ...]
    state_event_rows: tuple[dict[str, object], ...]
    input_rows: int
    excluded_outside_request: int = 0
    excluded_outside_range: int = 0
    excluded_duplicates: int = 0

    @property
    def excluded_rows(self) -> int:
        return (
            self.excluded_outside_request
            + self.excluded_outside_range
            + self.excluded_duplicates
        )


@dataclass(frozen=True)
class FinMindHistoricalEvidenceImportSummary:
    """Bounded import result; suspension events remain canonical-only for now."""

    dry_run: bool
    import_scope: str
    start_date: str
    end_date: str
    requested_symbols: tuple[str, ...]
    requested_global_symbols: tuple[str, ...]
    fetched_records: Mapping[str, int]
    normalized_action_rows: int
    canonical_state_event_rows: int
    excluded_rows: int
    verified_identity_rows: int
    unresolved_identity_rows: int
    action_rows_submitted: int
    state_event_rows_persisted: int
    source_payload_hashes: tuple[str, ...]
    source_retrieved_at: tuple[str, ...]
    database_counts: Mapping[str, int] = field(default_factory=lambda: {})
    reason_codes: tuple[str, ...] = (
        "FINMIND_HISTORICAL_VINTAGE_UNAVAILABLE",
        "FIRST_OBSERVED_AT_RETRIEVAL",
        "COMPLETE_ACTION_COVERAGE_NOT_ESTABLISHED",
        "SECURITY_STATE_PERSISTENCE_CONTRACT_NOT_CONFIGURED",
    )
    status: str = "RESEARCH_ONLY"
    usage_scope: str = "HISTORICAL_EVIDENCE_RESEARCH_ONLY"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "usage_scope": self.usage_scope,
            "dry_run": self.dry_run,
            "import_scope": self.import_scope,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "requested_symbols": list(self.requested_symbols),
            "requested_global_symbols": list(self.requested_global_symbols),
            "fetched_records": dict(self.fetched_records),
            "normalized_action_rows": self.normalized_action_rows,
            "canonical_state_event_rows": self.canonical_state_event_rows,
            "excluded_rows": self.excluded_rows,
            "verified_identity_rows": self.verified_identity_rows,
            "unresolved_identity_rows": self.unresolved_identity_rows,
            "action_rows_submitted": self.action_rows_submitted,
            "state_event_rows_persisted": self.state_event_rows_persisted,
            "source_payload_hashes": list(self.source_payload_hashes),
            "source_retrieved_at": list(self.source_retrieved_at),
            "database_counts": dict(self.database_counts),
            "reason_codes": list(self.reason_codes),
        }
