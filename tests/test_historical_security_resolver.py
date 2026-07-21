from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.data.canonical import (
    HistoricalSecurityResolver,
    ListingPeriodIdentity,
)


HASH = "a" * 64
DECISION_AT = datetime(2024, 1, 2, 6, 30, tzinfo=timezone.utc)
DEFAULT_EFFECTIVE_FROM = date(1962, 2, 9)
DEFAULT_AVAILABLE_AT = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _identity(
    *,
    listing_period_id: str = "listing-2330-1962",
    security_id: int | None = 2330,
    market: str = "TWSE",
    effective_from: date = DEFAULT_EFFECTIVE_FROM,
    effective_to: date | None = None,
    available_at: datetime = DEFAULT_AVAILABLE_AT,
    first_observed_at: datetime | None = None,
    point_in_time_status: str = "VERIFIED",
    resolution_status: str = "VERIFIED",
    usage_scope: str = "POINT_IN_TIME_IDENTITY",
    system_status: str = "PASS",
    reason_codes: tuple[str, ...] = (),
) -> ListingPeriodIdentity:
    return ListingPeriodIdentity(
        listing_period_id=listing_period_id,
        security_id=security_id,
        isin="TW0002330008",
        market=market,
        source_symbol="2330",
        asset_type="COMMON_STOCK",
        effective_from=effective_from,
        effective_to=effective_to,
        available_at=available_at,
        first_observed_at=first_observed_at or available_at,
        source_id=1,
        source_dataset="listing_history",
        source_version="v1",
        source_revision_hash=HASH,
        source_payload_hash="b" * 64,
        resolution_status=resolution_status,
        available_at_basis="VERSIONED_SNAPSHOT",
        point_in_time_status=point_in_time_status,
        usage_scope=usage_scope,
        system_status=system_status,
        reason_codes=reason_codes,
    )


def test_resolver_requires_independent_unique_identity() -> None:
    resolver = HistoricalSecurityResolver((_identity(),))

    resolved = resolver.resolve(
        source_symbol="2330",
        scheduled_market="TWSE",
        trade_date=date(2024, 1, 2),
        decision_at=DECISION_AT,
    )

    assert resolved.identity is not None
    assert resolved.identity.listing_period_id == "listing-2330-1962"
    assert resolved.point_in_time_eligible is True
    assert resolved.reason_codes == ()


def test_scheduled_market_is_only_a_consistency_check() -> None:
    resolver = HistoricalSecurityResolver((_identity(),))

    result = resolver.resolve(
        source_symbol="2330",
        scheduled_market="TPEX",
        trade_date=date(2024, 1, 2),
        decision_at=DECISION_AT,
    )

    assert result.identity is None
    assert result.reason_codes == ("SCHEDULED_MARKET_IDENTITY_MISMATCH",)


def test_cross_market_symbol_collision_fails_closed() -> None:
    resolver = HistoricalSecurityResolver(
        (_identity(), _identity(listing_period_id="tpex-2330", market="TPEX"))
    )

    result = resolver.resolve(
        source_symbol="2330",
        scheduled_market="TWSE",
        trade_date=date(2024, 1, 2),
        decision_at=DECISION_AT,
    )

    assert result.identity is None
    assert result.reason_codes == ("HISTORICAL_IDENTITY_AMBIGUOUS",)


def test_sequential_symbol_reuse_resolves_by_trade_date() -> None:
    resolver = HistoricalSecurityResolver(
        (
            _identity(
                listing_period_id="old",
                security_id=1,
                effective_from=date(1990, 1, 1),
                effective_to=date(2010, 1, 1),
            ),
            _identity(
                listing_period_id="new",
                security_id=2,
                effective_from=date(2010, 1, 1),
            ),
        )
    )

    result = resolver.resolve(
        source_symbol="2330",
        scheduled_market="TWSE",
        trade_date=date(2024, 1, 2),
        decision_at=DECISION_AT,
    )

    assert result.identity is not None
    assert result.identity.listing_period_id == "new"


def test_overlapping_verified_listing_periods_are_rejected() -> None:
    with pytest.raises(ValueError, match="overlap"):
        _ = HistoricalSecurityResolver(
            (
                _identity(effective_from=date(2000, 1, 1)),
                _identity(
                    listing_period_id="duplicate",
                    security_id=99,
                    effective_from=date(2020, 1, 1),
                ),
            )
        )


def test_late_or_unverified_identity_never_becomes_model_eligible() -> None:
    late = HistoricalSecurityResolver(
        (_identity(available_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),)
    ).resolve(
        source_symbol="2330",
        scheduled_market="TWSE",
        trade_date=date(2024, 1, 2),
        decision_at=DECISION_AT,
    )
    research = HistoricalSecurityResolver(
        (
            _identity(
                security_id=None,
                resolution_status="UNRESOLVED",
                point_in_time_status="UNVERIFIED",
                usage_scope="IDENTITY_RESEARCH_ONLY",
                system_status="RESEARCH_ONLY",
                reason_codes=("FIRST_OBSERVED_ONLY",),
            ),
        )
    ).resolve(
        source_symbol="2330",
        scheduled_market="TWSE",
        trade_date=date(2024, 1, 2),
        decision_at=DECISION_AT,
    )

    assert late.reason_codes == ("HISTORICAL_IDENTITY_NOT_FOUND",)
    assert research.reason_codes == ("HISTORICAL_IDENTITY_AMBIGUOUS",)
    assert not late.point_in_time_eligible
    assert not research.point_in_time_eligible


def test_conflict_evidence_invalidates_an_overlapping_verified_period() -> None:
    conflict = _identity(
        listing_period_id="conflict-evidence",
        security_id=None,
        resolution_status="CONFLICT",
        point_in_time_status="UNVERIFIED",
        usage_scope="IDENTITY_RESEARCH_ONLY",
        system_status="FAIL",
        reason_codes=("SOURCE_CONTRADICTION",),
    )
    resolver = HistoricalSecurityResolver((_identity(), conflict))

    result = resolver.resolve(
        source_symbol="2330",
        scheduled_market="TWSE",
        trade_date=date(2024, 1, 2),
        decision_at=DECISION_AT,
    )

    assert result.identity is None
    assert result.reason_codes == ("HISTORICAL_IDENTITY_CONFLICT",)


def test_conflict_evidence_after_decision_does_not_change_historical_resolution() -> (
    None
):
    future_conflict_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    future_conflict = _identity(
        listing_period_id="future-conflict",
        security_id=None,
        available_at=future_conflict_at,
        first_observed_at=future_conflict_at,
        resolution_status="CONFLICT",
        point_in_time_status="UNVERIFIED",
        usage_scope="IDENTITY_RESEARCH_ONLY",
        system_status="FAIL",
        reason_codes=("SOURCE_CONTRADICTION",),
    )
    resolver = HistoricalSecurityResolver((_identity(), future_conflict))

    result = resolver.resolve(
        source_symbol="2330",
        scheduled_market="TWSE",
        trade_date=date(2024, 1, 2),
        decision_at=DECISION_AT,
    )

    assert result.identity is not None
    assert result.identity.listing_period_id == "listing-2330-1962"
    assert result.point_in_time_eligible is True
    assert result.reason_codes == ()


def test_listing_identity_rejects_backdated_snapshot_availability() -> None:
    with pytest.raises(ValueError, match="first observation"):
        _ = _identity(
            available_at=datetime(2019, 1, 1, tzinfo=timezone.utc),
            first_observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
