"""Build auditable as-of feature snapshots from release-timestamped observations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import final
from zoneinfo import ZoneInfo

from src.core.horizon import PRODUCTION_HORIZON, require_production_horizon
from src.data.security_master import Market, SecurityMaster, SecurityRecord


TAIPEI = ZoneInfo("Asia/Taipei")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, kw_only=True)
class FeatureObservation:
    """One released feature value bound to a stable listing identity."""

    security_id: int
    listing_period_id: str
    market: Market
    symbol: str
    feature_name: str
    value: object
    data_date: date
    available_at: datetime
    first_observed_at: datetime
    available_at_basis: str
    point_in_time_status: str
    usage_scope: str
    reason_codes: tuple[str, ...]
    source: str
    source_version: str
    source_revision_hash: str
    revision_id: str = "original"
    is_critical: bool = False

    def __post_init__(self) -> None:
        if self.security_id < 1:
            raise ValueError("security_id must be positive")
        if not self.listing_period_id.strip():
            raise ValueError("listing_period_id is required")
        if (
            not self.symbol.strip()
            or not self.feature_name.strip()
            or not self.source.strip()
        ):
            raise ValueError("symbol, feature_name and source are required")
        if not self.source_version.strip() or not self.revision_id.strip():
            raise ValueError("source_version and revision_id are required")
        if len(self.source_revision_hash) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.source_revision_hash
        ):
            raise ValueError("source_revision_hash must be a lowercase SHA-256 digest")
        _require_aware(self.available_at, "available_at")
        _require_aware(self.first_observed_at, "first_observed_at")
        if self.available_at_basis not in {
            "OFFICIAL_PUBLICATION_AT",
            "VERSIONED_SNAPSHOT",
            "FIRST_OBSERVED_AT_RETRIEVAL",
        }:
            raise ValueError("unsupported feature available_at_basis")
        if self.available_at_basis == "OFFICIAL_PUBLICATION_AT":
            if self.available_at > self.first_observed_at:
                raise ValueError("feature availability follows first observation")
        elif self.available_at != self.first_observed_at:
            raise ValueError(
                "feature snapshot availability must equal first observation"
            )
        if self.point_in_time_status not in {"VERIFIED", "UNVERIFIED"}:
            raise ValueError("unsupported feature point_in_time_status")
        if self.usage_scope not in {
            "POINT_IN_TIME_FEATURE",
            "FEATURE_RESEARCH_ONLY",
        }:
            raise ValueError("unsupported feature usage_scope")
        if self.point_in_time_status == "VERIFIED":
            if (
                self.available_at_basis == "FIRST_OBSERVED_AT_RETRIEVAL"
                or self.usage_scope != "POINT_IN_TIME_FEATURE"
                or self.reason_codes
            ):
                raise ValueError("verified feature exceeds its evidence")
        elif self.usage_scope != "FEATURE_RESEARCH_ONLY" or not self.reason_codes:
            raise ValueError("unverified feature requires research reasons")

    @property
    def point_in_time_eligible(self) -> bool:
        return (
            self.point_in_time_status == "VERIFIED"
            and self.usage_scope == "POINT_IN_TIME_FEATURE"
        )


@dataclass(frozen=True)
class SnapshotRow:
    decision_at: datetime
    horizon: int
    security: SecurityRecord
    features: Mapping[str, object]
    feature_available_ats: Mapping[str, datetime]
    missing_features: tuple[str, ...]
    missing_critical_features: tuple[str, ...]
    source_dates: Mapping[str, date]
    latest_available_at: datetime | None


@dataclass(frozen=True)
class PointInTimeSnapshot:
    decision_at: datetime
    decision_date: date
    horizon: int
    rows: tuple[SnapshotRow, ...]
    excluded_future_observation_count: int
    excluded_unverified_observation_count: int

    def audit_available_at(self) -> tuple[str, ...]:
        violations: list[str] = []
        for row in self.rows:
            for feature_name, available_at in row.feature_available_ats.items():
                if available_at > self.decision_at:
                    violations.append(
                        f"{row.security.market.value}:{row.security.symbol}:{feature_name}"
                    )
        return tuple(violations)


@final
class PointInTimeDatasetBuilder:
    """Select the latest unambiguous revision public at decision time."""

    def __init__(
        self,
        *,
        security_master: SecurityMaster,
        observations: Iterable[FeatureObservation],
        expected_features: Sequence[str],
        critical_features: Sequence[str] = (),
    ) -> None:
        self.security_master: SecurityMaster = security_master
        self.observations: tuple[FeatureObservation, ...] = tuple(observations)
        self.expected_features: tuple[str, ...] = tuple(
            dict.fromkeys(expected_features)
        )
        self.critical_features: frozenset[str] = frozenset(critical_features)
        unknown = self.critical_features.difference(self.expected_features)
        if unknown:
            raise ValueError(
                f"critical features are not expected features: {sorted(unknown)}"
            )

    def build(
        self,
        *,
        decision_at: datetime,
        horizon: int = PRODUCTION_HORIZON,
    ) -> PointInTimeSnapshot:
        _require_aware(decision_at, "decision_at")
        _ = require_production_horizon(horizon)
        decision_date = decision_at.astimezone(TAIPEI).date()
        universe = self.security_master.common_stock_universe(
            decision_date,
            decision_at=decision_at,
            horizon=horizon,
            include_non_active=True,
        )

        released = [
            observation
            for observation in self.observations
            if observation.available_at <= decision_at
            and observation.point_in_time_eligible
        ]
        future_release_count = sum(
            observation.available_at > decision_at for observation in self.observations
        )
        unverified_count = sum(
            observation.available_at <= decision_at
            and not observation.point_in_time_eligible
            for observation in self.observations
        )

        by_listing_period: dict[str, list[FeatureObservation]] = {}
        for observation in released:
            by_listing_period.setdefault(observation.listing_period_id, []).append(
                observation
            )

        rows: list[SnapshotRow] = []
        for security in universe.securities:
            observations = by_listing_period.get(security.listing_period_id, ())
            self._assert_identity_matches(security, observations)
            latest = self._latest_observations(observations)
            features = {
                name: latest[name].value
                for name in self.expected_features
                if name in latest and latest[name].value is not None
            }
            missing = tuple(
                name for name in self.expected_features if name not in features
            )
            missing_critical = tuple(
                name for name in missing if name in self.critical_features
            )
            feature_times = {
                name: latest[name].available_at
                for name in self.expected_features
                if name in latest
            }
            source_dates: dict[str, date] = {}
            for name in self.expected_features:
                observation = latest.get(name)
                if observation is None:
                    continue
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
            decision_date=decision_date,
            horizon=horizon,
            rows=tuple(rows),
            excluded_future_observation_count=future_release_count,
            excluded_unverified_observation_count=unverified_count,
        )
        violations = snapshot.audit_available_at()
        if violations:
            raise AssertionError(f"point-in-time audit failed: {violations}")
        return snapshot

    @staticmethod
    def _assert_identity_matches(
        security: SecurityRecord,
        observations: Iterable[FeatureObservation],
    ) -> None:
        for observation in observations:
            observed_identity = (
                observation.security_id,
                observation.market,
                observation.symbol,
            )
            expected_identity = (security.security_id, security.market, security.symbol)
            if observed_identity != expected_identity:
                raise ValueError(
                    "feature identity conflicts with security master for "
                    + f"listing_period_id={security.listing_period_id}"
                )

    @staticmethod
    def _latest_observations(
        observations: Iterable[FeatureObservation],
    ) -> dict[str, FeatureObservation]:
        by_feature: dict[str, list[FeatureObservation]] = {}
        for observation in observations:
            by_feature.setdefault(observation.feature_name, []).append(observation)

        latest: dict[str, FeatureObservation] = {}
        for feature_name, candidates in by_feature.items():
            PointInTimeDatasetBuilder._assert_no_conflicting_revisions(
                feature_name,
                candidates,
            )
            latest_data_date = max(candidate.data_date for candidate in candidates)
            same_period = [
                candidate
                for candidate in candidates
                if candidate.data_date == latest_data_date
            ]
            latest_available_at = max(
                candidate.available_at for candidate in same_period
            )
            same_release = [
                candidate
                for candidate in same_period
                if candidate.available_at == latest_available_at
            ]
            latest[feature_name] = same_release[0]
        return latest

    @staticmethod
    def _assert_no_conflicting_revisions(
        feature_name: str,
        candidates: Iterable[FeatureObservation],
    ) -> None:
        releases: dict[
            tuple[date, datetime],
            tuple[object, str, str, str, str],
        ] = {}
        for candidate in candidates:
            release_key = (candidate.data_date, candidate.available_at)
            fingerprint = (
                candidate.value,
                candidate.source,
                candidate.source_version,
                candidate.source_revision_hash,
                candidate.revision_id,
            )
            existing = releases.setdefault(release_key, fingerprint)
            if existing != fingerprint:
                raise ValueError(
                    "conflicting feature revisions at the same available_at for "
                    + f"listing_period_id={candidate.listing_period_id}, "
                    + f"feature={feature_name}, data_date={candidate.data_date.isoformat()}"
                )


def feature_is_available(available_at: datetime, decision_at: datetime) -> bool:
    """Timezone-safe release test, including US-close/Taiwan-decision ordering."""

    _require_aware(available_at, "available_at")
    _require_aware(decision_at, "decision_at")
    return available_at <= decision_at
