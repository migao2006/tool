"""Fail-closed contracts for promoting raw historical data."""

from .contracts import (
    CANONICAL_DAILY_BAR_SCHEMA_VERSION,
    CanonicalDailyBar,
    PromotionResult,
)
from .evidence_contracts import HistoricalDecisionContext, ListingPeriodIdentity
from .daily_bar_promotion import CanonicalDailyBarPromotionService
from .historical_security_resolver import (
    HistoricalIdentityResolution,
    HistoricalSecurityResolver,
)
from .supabase_repository import (
    ListingPeriodEvidenceRepository,
    ListingPeriodEvidenceSnapshot,
    PointInTimeEvidenceReadError,
)

__all__ = [
    "CANONICAL_DAILY_BAR_SCHEMA_VERSION",
    "CanonicalDailyBar",
    "CanonicalDailyBarPromotionService",
    "HistoricalDecisionContext",
    "HistoricalIdentityResolution",
    "HistoricalSecurityResolver",
    "ListingPeriodIdentity",
    "ListingPeriodEvidenceRepository",
    "ListingPeriodEvidenceSnapshot",
    "PointInTimeEvidenceReadError",
    "PromotionResult",
]
