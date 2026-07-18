"""Build auditable as-of feature snapshots from release-timestamped observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Sequence

from src.core.horizon import PRODUCTION_HORIZON, require_production_horizon
from src.data.security_master import SecurityMaster, SecurityRecord


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class FeatureObservation:
    symbol: str
    feature_name: str
    value: Any
    data_date: date
    available_at: datetime
    source: str
    revision_id: str = "original"
    is_critical: bool = False

    def __post_init__(self) -> None:
        if not self.symbol or not self.feature_name or not self.source:
            raise ValueError("symbol, feature_name and source are required")
        _require_aware(self.available_at, "available_at")


@dataclass(frozen=True)
class SnapshotRow:
    decision_at: datetime
    horizon: int
    security: SecurityRecord
    features: Mapping[str, Any]
    feature_available_ats: Mapping[str, datetime]
    missing_features: tuple[str, ...]
    missing_critical_features: tuple[str, ...]
    source_dates: Mapping[str, date]
    latest_available_at: datetime | None


@dataclass(frozen=True)
class PointInTimeSnapshot:
    decision_at: datetime
    horizon: int
    rows: tuple[SnapshotRow, ...]
    excluded_future_observation_count: int

    def audit_available_at(self) -> tuple[str, ...]:
        violations: list[str] = []
        for row in self.rows:
            for feature_name, available_at in row.feature_available_ats.items():
                if available_at > self.decision_at:
                    violations.append(f"{row.security.symbol}:{feature_name}")
        return tuple(violations)


class PointInTimeDatasetBuilder:
    """Select the latest revision that was actually public at decision time."""

    def __init__(
        self,
        *,
        security_master: SecurityMaster,
        observations: Iterable[FeatureObservation],
        expected_features: Sequence[str],
        critical_features: Sequence[str] = (),
    ) -> None:
        self.security_master = security_master
        self.observations = tuple(observations)
        self.expected_features = tuple(dict.fromkeys(expected_features))
        self.critical_features = frozenset(critical_features)
        unknown = self.critical_features.difference(self.expected_features)
        if unknown:
            raise ValueError(f"critical features are not expected features: {sorted(unknown)}")

    def build(
        self,
        *,
        decision_at: datetime,
        horizon: int = PRODUCTION_HORIZON,
    ) -> PointInTimeSnapshot:
        _require_aware(decision_at, "decision_at")
        require_production_horizon(horizon)
        universe = self.security_master.common_stock_universe(
            decision_at.date(),
            decision_at=decision_at,
            horizon=horizon,
            include_non_active=True,
        )
        eligible = [observation for observation in self.observations if observation.available_at <= decision_at]
        future_count = len(self.observations) - len(eligible)

        by_symbol: dict[str, list[FeatureObservation]] = {}
        for observation in eligible:
            by_symbol.setdefault(observation.symbol, []).append(observation)

        rows: list[SnapshotRow] = []
        for security in universe.securities:
            latest: dict[str, FeatureObservation] = {}
            for observation in by_symbol.get(security.symbol, ()):  # no forward fill across symbols
                current = latest.get(observation.feature_name)
                key = (observation.available_at, observation.revision_id)
                if current is None or key > (current.available_at, current.revision_id):
                    latest[observation.feature_name] = observation
            features = {
                name: latest[name].value
                for name in self.expected_features
                if name in latest and latest[name].value is not None
            }
            missing = tuple(name for name in self.expected_features if name not in features)
            missing_critical = tuple(name for name in missing if name in self.critical_features)
            feature_times = {name: observation.available_at for name, observation in latest.items()}
            source_dates: dict[str, date] = {}
            for observation in latest.values():
                previous = source_dates.get(observation.source)
                if previous is None or observation.data_date > previous:
                    source_dates[observation.source] = observation.data_date
            rows.append(
                SnapshotRow(
                    decision_at=decision_at,
                    horizon=horizon,
                    security=security,
                    features=features,
                    feature_available_ats=feature_times,
                    missing_features=missing,
                    missing_critical_features=missing_critical,
                    source_dates=source_dates,
                    latest_available_at=max(feature_times.values(), default=None),
                )
            )
        snapshot = PointInTimeSnapshot(
            decision_at=decision_at,
            horizon=horizon,
            rows=tuple(rows),
            excluded_future_observation_count=future_count,
        )
        violations = snapshot.audit_available_at()
        if violations:
            raise AssertionError(f"point-in-time audit failed: {violations}")
        return snapshot


def feature_is_available(available_at: datetime, decision_at: datetime) -> bool:
    """Timezone-safe release test, including US-close/Taiwan-decision ordering."""

    _require_aware(available_at, "available_at")
    _require_aware(decision_at, "decision_at")
    return available_at <= decision_at
