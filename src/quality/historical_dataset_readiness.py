"""Explain whether archived history may enter the point-in-time dataset builder."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HistoricalDatasetReadinessMetrics:
    """Evidence counts from one immutable audit snapshot.

    ``None`` means the metric could not be verified.  It is never treated as
    zero or silently accepted.
    """

    archive_integrity_status: str
    archive_object_count: int | None
    archive_row_count: int | None
    twse_archive_symbol_count: int | None
    tpex_archive_symbol_count: int | None
    twse_pit_covered_archive_symbol_count: int | None
    tpex_pit_covered_archive_symbol_count: int | None
    pit_covered_trading_session_count: int | None
    twse_verified_listing_period_count: int | None
    tpex_verified_listing_period_count: int | None
    conflicting_listing_period_count: int | None
    twse_verified_calendar_session_count: int | None
    tpex_verified_calendar_session_count: int | None
    verified_security_state_count: int | None
    verified_company_action_coverage_count: int | None
    unresolved_delisting_count: int | None
    canonical_contract_object_count: int | None
    canonical_production_row_count: int | None

    def __post_init__(self) -> None:
        if self.archive_integrity_status not in {"PASS", "FAIL", "UNKNOWN"}:
            raise ValueError("unsupported archive_integrity_status")
        for value in self._counts():
            if value is not None and value < 0:
                raise ValueError("readiness counts must not be negative")

    def _counts(self) -> tuple[int | None, ...]:
        return (
            self.archive_object_count,
            self.archive_row_count,
            self.twse_archive_symbol_count,
            self.tpex_archive_symbol_count,
            self.twse_pit_covered_archive_symbol_count,
            self.tpex_pit_covered_archive_symbol_count,
            self.pit_covered_trading_session_count,
            self.twse_verified_listing_period_count,
            self.tpex_verified_listing_period_count,
            self.conflicting_listing_period_count,
            self.twse_verified_calendar_session_count,
            self.tpex_verified_calendar_session_count,
            self.verified_security_state_count,
            self.verified_company_action_coverage_count,
            self.unresolved_delisting_count,
            self.canonical_contract_object_count,
            self.canonical_production_row_count,
        )


@dataclass(frozen=True)
class HistoricalDatasetReadinessThresholds:
    """Transparent prerequisites; these are data gates, not model acceptance."""

    minimum_archive_rows: int = 1
    minimum_twse_symbols: int = 300
    minimum_tpex_symbols: int = 200
    minimum_calendar_sessions: int = 1_200
    minimum_security_states: int = 1
    minimum_company_action_coverage_rows: int = 1
    minimum_canonical_rows: int = 1

    def __post_init__(self) -> None:
        if (
            min(
                self.minimum_archive_rows,
                self.minimum_twse_symbols,
                self.minimum_tpex_symbols,
                self.minimum_calendar_sessions,
                self.minimum_security_states,
                self.minimum_company_action_coverage_rows,
                self.minimum_canonical_rows,
            )
            <= 0
        ):
            raise ValueError("readiness thresholds must be positive")


@dataclass(frozen=True)
class HistoricalDatasetReadinessResult:
    canonicalization_ready: bool
    canonicalization_status: str
    dataset_build_ready: bool
    readiness_status: str
    system_status: str
    canonicalization_reason_codes: tuple[str, ...]
    reason_codes: tuple[str, ...]


_METRIC_UNAVAILABLE_REASONS = (
    ("archive_object_count", "ARCHIVE_OBJECT_COUNT_UNAVAILABLE"),
    ("archive_row_count", "ARCHIVE_ROW_COUNT_UNAVAILABLE"),
    ("twse_archive_symbol_count", "TWSE_ARCHIVE_SYMBOL_COUNT_UNAVAILABLE"),
    ("tpex_archive_symbol_count", "TPEX_ARCHIVE_SYMBOL_COUNT_UNAVAILABLE"),
    (
        "twse_pit_covered_archive_symbol_count",
        "TWSE_PIT_COVERED_SYMBOL_COUNT_UNAVAILABLE",
    ),
    (
        "tpex_pit_covered_archive_symbol_count",
        "TPEX_PIT_COVERED_SYMBOL_COUNT_UNAVAILABLE",
    ),
    (
        "pit_covered_trading_session_count",
        "PIT_COVERED_TRADING_SESSION_COUNT_UNAVAILABLE",
    ),
    (
        "twse_verified_listing_period_count",
        "TWSE_VERIFIED_LISTING_PERIOD_COUNT_UNAVAILABLE",
    ),
    (
        "tpex_verified_listing_period_count",
        "TPEX_VERIFIED_LISTING_PERIOD_COUNT_UNAVAILABLE",
    ),
    ("conflicting_listing_period_count", "LISTING_PERIOD_CONFLICT_COUNT_UNAVAILABLE"),
    (
        "twse_verified_calendar_session_count",
        "TWSE_VERIFIED_CALENDAR_COUNT_UNAVAILABLE",
    ),
    (
        "tpex_verified_calendar_session_count",
        "TPEX_VERIFIED_CALENDAR_COUNT_UNAVAILABLE",
    ),
    ("verified_security_state_count", "SECURITY_STATE_COUNT_UNAVAILABLE"),
    (
        "verified_company_action_coverage_count",
        "COMPANY_ACTION_COVERAGE_COUNT_UNAVAILABLE",
    ),
    ("unresolved_delisting_count", "UNRESOLVED_DELISTING_COUNT_UNAVAILABLE"),
    ("canonical_contract_object_count", "CANONICAL_CONTRACT_UNAVAILABLE"),
    ("canonical_production_row_count", "CANONICAL_ROW_COUNT_UNAVAILABLE"),
)


def assess_historical_dataset_readiness(
    metrics: HistoricalDatasetReadinessMetrics,
    *,
    thresholds: HistoricalDatasetReadinessThresholds | None = None,
) -> HistoricalDatasetReadinessResult:
    """Apply only hard evidence gates; never infer readiness from raw row volume."""

    limits = thresholds or HistoricalDatasetReadinessThresholds()
    prerequisite_reasons: list[str] = []
    if metrics.archive_integrity_status == "FAIL":
        prerequisite_reasons.append("ARCHIVE_INTEGRITY_FAILED")
    elif metrics.archive_integrity_status == "UNKNOWN":
        prerequisite_reasons.append("ARCHIVE_INTEGRITY_UNVERIFIED")

    for field, reason in _METRIC_UNAVAILABLE_REASONS:
        if field != "canonical_production_row_count" and getattr(metrics, field) is None:
            prerequisite_reasons.append(reason)

    def below(value: int | None, minimum: int, reason: str) -> None:
        if value is not None and value < minimum:
            prerequisite_reasons.append(reason)

    below(metrics.archive_object_count, 1, "HISTORICAL_ARCHIVE_EMPTY")
    below(
        metrics.archive_row_count,
        limits.minimum_archive_rows,
        "HISTORICAL_ARCHIVE_ROWS_INSUFFICIENT",
    )
    below(
        metrics.twse_archive_symbol_count,
        limits.minimum_twse_symbols,
        "TWSE_ARCHIVE_SYMBOL_COVERAGE_INSUFFICIENT",
    )
    below(
        metrics.tpex_archive_symbol_count,
        limits.minimum_tpex_symbols,
        "TPEX_ARCHIVE_SYMBOL_COVERAGE_INSUFFICIENT",
    )
    below(
        metrics.twse_pit_covered_archive_symbol_count,
        limits.minimum_twse_symbols,
        "TWSE_POINT_IN_TIME_COVERAGE_INTERSECTION_INSUFFICIENT",
    )
    below(
        metrics.tpex_pit_covered_archive_symbol_count,
        limits.minimum_tpex_symbols,
        "TPEX_POINT_IN_TIME_COVERAGE_INTERSECTION_INSUFFICIENT",
    )
    below(
        metrics.pit_covered_trading_session_count,
        limits.minimum_calendar_sessions,
        "POINT_IN_TIME_SESSION_COVERAGE_INTERSECTION_INSUFFICIENT",
    )
    below(
        metrics.twse_verified_listing_period_count,
        limits.minimum_twse_symbols,
        "TWSE_LISTING_IDENTITY_COVERAGE_INSUFFICIENT",
    )
    below(
        metrics.tpex_verified_listing_period_count,
        limits.minimum_tpex_symbols,
        "TPEX_LISTING_IDENTITY_COVERAGE_INSUFFICIENT",
    )
    if metrics.conflicting_listing_period_count not in {None, 0}:
        prerequisite_reasons.append("LISTING_IDENTITY_CONFLICTS_PRESENT")
    below(
        metrics.twse_verified_calendar_session_count,
        limits.minimum_calendar_sessions,
        "TWSE_CALENDAR_COVERAGE_INSUFFICIENT",
    )
    below(
        metrics.tpex_verified_calendar_session_count,
        limits.minimum_calendar_sessions,
        "TPEX_CALENDAR_COVERAGE_INSUFFICIENT",
    )
    below(
        metrics.verified_security_state_count,
        limits.minimum_security_states,
        "SECURITY_STATE_HISTORY_EMPTY",
    )
    below(
        metrics.verified_company_action_coverage_count,
        limits.minimum_company_action_coverage_rows,
        "COMPANY_ACTION_COVERAGE_EMPTY",
    )
    if metrics.unresolved_delisting_count not in {None, 0}:
        prerequisite_reasons.append("DELISTING_IDENTITIES_UNRESOLVED")

    canonicalization_reasons = tuple(dict.fromkeys(prerequisite_reasons))
    canonicalization_ready = not canonicalization_reasons
    dataset_reasons = list(canonicalization_reasons)
    if metrics.canonical_production_row_count is None:
        dataset_reasons.append("CANONICAL_ROW_COUNT_UNAVAILABLE")
    elif metrics.canonical_production_row_count < limits.minimum_canonical_rows:
        dataset_reasons.append("CANONICAL_PRODUCTION_ROWS_EMPTY")
    unique_reasons = tuple(dict.fromkeys(dataset_reasons))
    dataset_ready = not unique_reasons
    return HistoricalDatasetReadinessResult(
        canonicalization_ready=canonicalization_ready,
        canonicalization_status=(
            "READY_FOR_CANONICALIZATION" if canonicalization_ready else "BLOCKED"
        ),
        dataset_build_ready=dataset_ready,
        readiness_status=(
            "READY_FOR_DATASET_BUILD"
            if dataset_ready
            else "READY_FOR_CANONICALIZATION"
            if canonicalization_ready
            else "BLOCKED"
        ),
        # Data readiness alone can never approve a model for production.
        system_status=(
            "FAIL" if metrics.archive_integrity_status == "FAIL" else "RESEARCH_ONLY"
        ),
        canonicalization_reason_codes=canonicalization_reasons,
        reason_codes=unique_reasons,
    )
