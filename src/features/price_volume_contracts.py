"""Auditable contracts for shared raw price/volume research features."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from numbers import Real

from .price_volume_schema import (
    PRICE_VOLUME_AVAILABILITY_MODES,
    PRICE_VOLUME_FEATURE_FORMULAS,
    PRICE_VOLUME_FEATURE_NAMES,
    PRICE_VOLUME_PRICE_BASIS,
    RESEARCH_SCHEDULING_HINT_REASON,
    price_volume_feature_spec,
)


_TWSE_SPEC = price_volume_feature_spec("TWSE")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def strict_point_in_time_audit_pass(
    availability_mode: str,
    hard_fail_reason_codes: tuple[str, ...],
    research_limitation_reason_codes: tuple[str, ...],
) -> bool:
    """Return true only for strict evidence without any PIT warning."""

    return availability_mode == "STRICT_CANONICAL" and not any(
        "POINT_IN_TIME" in reason
        or "AVAILABLE_AT" in reason
        or reason
        in {
            "BAR_AVAILABLE_AFTER_DECISION",
            "DECISION_DATE_MISMATCH",
            "POINT_IN_TIME_VIOLATION",
        }
        for reason in (
            *hard_fail_reason_codes,
            *research_limitation_reason_codes,
        )
    )


@dataclass(frozen=True)
class FeatureValueAudit:
    """One value plus the exact source window and any fail-closed reasons."""

    feature_name: str
    value: float | None
    availability_mode: str
    available_at: datetime | None
    observed_available_at: datetime | None
    source_start_date: date | None
    source_end_date: date
    source_row_count: int
    source_available_at_bases: tuple[str, ...]
    reason_codes: tuple[str, ...]
    research_limitation_reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.feature_name not in PRICE_VOLUME_FEATURE_NAMES:
            raise ValueError("unsupported price/volume feature")
        if self.availability_mode not in PRICE_VOLUME_AVAILABILITY_MODES:
            raise ValueError("unsupported feature availability mode")
        if self.available_at is not None:
            _require_aware(self.available_at, "feature available_at")
        if self.observed_available_at is not None:
            _require_aware(
                self.observed_available_at,
                "feature observed_available_at",
            )
        if self.availability_mode == "STRICT_CANONICAL" and (
            self.available_at != self.observed_available_at
        ):
            raise ValueError("strict availability must preserve the observed timestamp")
        if self.source_start_date is not None:
            if self.source_start_date > self.source_end_date:
                raise ValueError("feature source range is reversed")
        if self.source_row_count < 0:
            raise ValueError("source_row_count cannot be negative")
        if self.source_row_count and not self.source_available_at_bases:
            raise ValueError(
                "source availability bases are required for non-empty windows"
            )
        if self.value is None and not self.reason_codes:
            raise ValueError("missing feature values require reason codes")
        if self.value is not None:
            if not isfinite(self.value):
                raise ValueError("feature values must be finite")
            if self.reason_codes:
                raise ValueError("failed feature values must not be released")
        if set(self.reason_codes).intersection(self.research_limitation_reason_codes):
            raise ValueError("hard-fail and research limitation reasons cannot overlap")
        if (
            self.availability_mode == "STRICT_CANONICAL"
            and self.research_limitation_reason_codes
        ):
            raise ValueError("strict feature audits cannot downgrade source failures")


@dataclass(frozen=True)
class PriceVolumeFeatureRow:
    """One venue-scoped row that cannot hide missing or future inputs."""

    security_id: int
    listing_period_id: str
    symbol: str
    decision_date: date
    decision_at: datetime
    horizon: int
    feature_schema_version: str
    feature_schema_hash: str
    price_basis: str
    availability_mode: str
    decision_close_price: float | None
    feature_values: Mapping[str, float | None]
    feature_audits: Mapping[str, FeatureValueAudit]
    latest_available_at: datetime | None
    latest_observed_available_at: datetime | None
    missing_features: tuple[str, ...]
    hard_fail_reason_codes: tuple[str, ...]
    research_limitation_reason_codes: tuple[str, ...]
    point_in_time_audit_pass: bool
    hard_fail: bool
    market: str = "TWSE"
    usage_scope: str = "FEATURE_RESEARCH_ONLY"
    system_status: str = "RESEARCH_ONLY"

    def __post_init__(self) -> None:
        if self.security_id <= 0:
            raise ValueError("security_id must be positive")
        if not self.listing_period_id.strip() or not self.symbol.strip():
            raise ValueError("listing_period_id and symbol are required")
        _require_aware(self.decision_at, "decision_at")
        spec = price_volume_feature_spec(self.market)
        if self.horizon != 5:
            raise ValueError("research features support only horizon=5")
        if self.feature_schema_version != spec.schema_version:
            raise ValueError("unexpected feature schema version")
        if self.feature_schema_hash != spec.schema_hash:
            raise ValueError("unexpected feature schema hash")
        if self.price_basis != PRICE_VOLUME_PRICE_BASIS:
            raise ValueError("unexpected feature price basis")
        if self.availability_mode not in PRICE_VOLUME_AVAILABILITY_MODES:
            raise ValueError("unsupported row availability mode")
        if self.decision_close_price is not None:
            close = self.decision_close_price
            if (
                isinstance(close, bool)
                or not isinstance(close, Real)
                or not isfinite(float(close))
                or close <= 0
            ):
                raise ValueError("decision_close_price must be finite and positive")
        if tuple(self.feature_values) != PRICE_VOLUME_FEATURE_NAMES:
            raise ValueError("feature_values do not match the frozen schema order")
        if tuple(self.feature_audits) != PRICE_VOLUME_FEATURE_NAMES:
            raise ValueError("feature_audits do not match the frozen schema order")
        if any(
            audit.availability_mode != self.availability_mode
            for audit in self.feature_audits.values()
        ):
            raise ValueError("feature audit availability modes do not match the row")
        expected_missing = tuple(
            name
            for name in PRICE_VOLUME_FEATURE_NAMES
            if self.feature_values[name] is None
        )
        if self.missing_features != expected_missing:
            raise ValueError("missing_features do not match feature_values")
        expected_hard_fail = bool(self.hard_fail_reason_codes or expected_missing)
        if self.hard_fail != expected_hard_fail:
            raise ValueError("hard_fail does not match feature audit results")
        if not expected_hard_fail and self.decision_close_price is None:
            raise ValueError("eligible feature rows require decision_close_price")
        if self.latest_available_at is not None:
            _require_aware(self.latest_available_at, "latest_available_at")
        if self.latest_observed_available_at is not None:
            _require_aware(
                self.latest_observed_available_at,
                "latest_observed_available_at",
            )
        expected_limitations = tuple(
            dict.fromkeys(
                reason
                for audit in self.feature_audits.values()
                for reason in audit.research_limitation_reason_codes
            )
        )
        if self.research_limitation_reason_codes != expected_limitations:
            raise ValueError("research limitations do not match feature audits")
        expected_pit_pass = strict_point_in_time_audit_pass(
            self.availability_mode,
            self.hard_fail_reason_codes,
            self.research_limitation_reason_codes,
        )
        if self.point_in_time_audit_pass != expected_pit_pass:
            raise ValueError("point_in_time_audit_pass is inconsistent")
        if self.usage_scope != "FEATURE_RESEARCH_ONLY":
            raise ValueError("feature rows must remain research-only")
        if self.system_status != "RESEARCH_ONLY":
            raise ValueError("feature rows cannot be promoted by this builder")


@dataclass(frozen=True)
class PriceVolumeFeatureBuildResult:
    input_row_count: int
    trading_sessions: tuple[date, ...]
    rows: tuple[PriceVolumeFeatureRow, ...]
    market: str = "TWSE"
    availability_mode: str = "STRICT_CANONICAL"
    feature_schema_version: str = _TWSE_SPEC.schema_version
    feature_schema_hash: str = _TWSE_SPEC.schema_hash
    system_status: str = "RESEARCH_ONLY"

    def __post_init__(self) -> None:
        if self.input_row_count < 0:
            raise ValueError("input_row_count cannot be negative")
        if tuple(sorted(set(self.trading_sessions))) != self.trading_sessions:
            raise ValueError("trading_sessions must be sorted and unique")
        spec = price_volume_feature_spec(self.market)
        if self.availability_mode not in PRICE_VOLUME_AVAILABILITY_MODES:
            raise ValueError("unsupported build availability mode")
        if any(row.availability_mode != self.availability_mode for row in self.rows):
            raise ValueError("row availability modes do not match the build")
        if self.feature_schema_version != spec.schema_version:
            raise ValueError("unexpected build schema version")
        if self.feature_schema_hash != spec.schema_hash:
            raise ValueError("unexpected build schema hash")
        if self.system_status != "RESEARCH_ONLY":
            raise ValueError("feature build must remain research-only")

    @property
    def hard_fail_count(self) -> int:
        return sum(row.hard_fail for row in self.rows)

    @property
    def reason_counts(self) -> Mapping[str, int]:
        return dict(
            Counter(
                reason for row in self.rows for reason in row.hard_fail_reason_codes
            )
        )


# Stable aliases keep the existing TWSE public contract source-compatible.
TwsePriceVolumeFeatureRow = PriceVolumeFeatureRow
TwsePriceVolumeFeatureBuildResult = PriceVolumeFeatureBuildResult


__all__ = [
    "FeatureValueAudit",
    "PriceVolumeFeatureBuildResult",
    "PriceVolumeFeatureRow",
    "PRICE_VOLUME_AVAILABILITY_MODES",
    "PRICE_VOLUME_FEATURE_FORMULAS",
    "PRICE_VOLUME_FEATURE_NAMES",
    "PRICE_VOLUME_PRICE_BASIS",
    "RESEARCH_SCHEDULING_HINT_REASON",
    "TwsePriceVolumeFeatureBuildResult",
    "TwsePriceVolumeFeatureRow",
    "strict_point_in_time_audit_pass",
]
