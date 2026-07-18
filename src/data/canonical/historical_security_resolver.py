"""Resolve historical symbols only through independently sourced listing periods."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import final

from .evidence_contracts import ListingPeriodIdentity


@dataclass(frozen=True)
class HistoricalIdentityResolution:
    identity: ListingPeriodIdentity | None
    point_in_time_eligible: bool
    reason_codes: tuple[str, ...]


@final
class HistoricalSecurityResolver:
    """Fail closed on market hints, ambiguity, reuse, or late identity evidence."""

    def __init__(self, identities: tuple[ListingPeriodIdentity, ...]) -> None:
        self._identities = identities
        self._validate_overlaps()

    def _validate_overlaps(self) -> None:
        verified = [
            identity
            for identity in self._identities
            if identity.resolution_status == "VERIFIED"
        ]
        for index, left in enumerate(verified):
            for right in verified[index + 1 :]:
                if (
                    left.market != right.market
                    or left.source_symbol != right.source_symbol
                    or left.listing_period_id == right.listing_period_id
                ):
                    continue
                left_end = left.effective_to or date.max
                right_end = right.effective_to or date.max
                if left.effective_from < right_end and right.effective_from < left_end:
                    raise ValueError(
                        "verified listing periods overlap for market and symbol"
                    )

    def resolve(
        self,
        *,
        source_symbol: str,
        scheduled_market: str,
        trade_date: date,
        decision_at: datetime,
    ) -> HistoricalIdentityResolution:
        if decision_at.tzinfo is None or decision_at.utcoffset() is None:
            raise ValueError("decision_at must be timezone-aware")
        cutoff = decision_at.astimezone(timezone.utc)
        candidates = [
            identity
            for identity in self._identities
            if identity.source_symbol == source_symbol
            and identity.asset_type == "COMMON_STOCK"
            and identity.covers(trade_date)
            and identity.available_at <= cutoff
        ]
        if any(identity.resolution_status == "CONFLICT" for identity in candidates):
            return HistoricalIdentityResolution(
                identity=None,
                point_in_time_eligible=False,
                reason_codes=("HISTORICAL_IDENTITY_CONFLICT",),
            )
        verified = [
            identity
            for identity in candidates
            if identity.resolution_status == "VERIFIED"
        ]
        if not candidates:
            return HistoricalIdentityResolution(
                identity=None,
                point_in_time_eligible=False,
                reason_codes=("HISTORICAL_IDENTITY_NOT_FOUND",),
            )
        if len(verified) != 1:
            return HistoricalIdentityResolution(
                identity=None,
                point_in_time_eligible=False,
                reason_codes=("HISTORICAL_IDENTITY_AMBIGUOUS",),
            )
        identity = verified[0]
        if identity.market != scheduled_market:
            return HistoricalIdentityResolution(
                identity=None,
                point_in_time_eligible=False,
                reason_codes=("SCHEDULED_MARKET_IDENTITY_MISMATCH",),
            )
        if (
            identity.point_in_time_status != "VERIFIED"
            or identity.usage_scope != "POINT_IN_TIME_IDENTITY"
            or identity.system_status != "PASS"
        ):
            return HistoricalIdentityResolution(
                identity=identity,
                point_in_time_eligible=False,
                reason_codes=("IDENTITY_POINT_IN_TIME_UNVERIFIED",),
            )
        return HistoricalIdentityResolution(
            identity=identity,
            point_in_time_eligible=True,
            reason_codes=(),
        )
