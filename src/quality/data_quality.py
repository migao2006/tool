"""Hard-fail data quality, tradability, liquidity and capacity gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Mapping

from src.core.horizon import PRODUCTION_HORIZON, require_production_horizon
from src.data.security_master import AssetType, SecurityRecord, TradingStatus


ZERO = Decimal("0")


def _decimal(value: Decimal | int | float | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


class Freshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    MISSING = "MISSING"


class QualityScope(str, Enum):
    """Separate live-decision inputs from future label/execution evidence."""

    DECISION = "DECISION"
    LABEL = "LABEL"


@dataclass(frozen=True)
class DataQualityConfig:
    minimum_history_sessions: int = 252
    minimum_adv20_ntd: Decimal = Decimal("5000000")
    max_adv_participation: Decimal = Decimal("0.01")
    maximum_source_age: timedelta = timedelta(days=7)
    exclude_attention: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "minimum_adv20_ntd", _decimal(self.minimum_adv20_ntd))
        object.__setattr__(self, "max_adv_participation", _decimal(self.max_adv_participation))
        if self.minimum_history_sessions < 1:
            raise ValueError("minimum_history_sessions must be positive")
        if self.minimum_adv20_ntd <= ZERO:
            raise ValueError("minimum_adv20_ntd must be positive")
        if not ZERO < self.max_adv_participation <= Decimal("1"):
            raise ValueError("max_adv_participation must be in (0, 1]")
        if self.maximum_source_age < timedelta(0):
            raise ValueError("maximum_source_age cannot be negative")


@dataclass(frozen=True)
class DataQualityInput:
    decision_at: datetime
    security: SecurityRecord
    history_sessions: int
    adv20_ntd: Decimal | int | float | str | None
    estimated_order_notional_ntd: Decimal | int | float | str
    has_corporate_action_data: bool
    has_executable_entry_price: bool
    has_executable_exit_price: bool
    expected_fields: tuple[str, ...]
    present_fields: tuple[str, ...]
    critical_fields: tuple[str, ...]
    source_dates: Mapping[str, date]
    latest_available_at: datetime | None
    horizon: int = PRODUCTION_HORIZON
    scope: QualityScope = QualityScope.DECISION
    source_available_at: Mapping[str, datetime] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.decision_at.tzinfo is None or self.decision_at.utcoffset() is None:
            raise ValueError("decision_at must be timezone-aware")
        object.__setattr__(
            self,
            "estimated_order_notional_ntd",
            _decimal(self.estimated_order_notional_ntd),
        )
        if self.adv20_ntd is not None:
            object.__setattr__(self, "adv20_ntd", _decimal(self.adv20_ntd))
        if self.latest_available_at is not None and (
            self.latest_available_at.tzinfo is None
            or self.latest_available_at.utcoffset() is None
        ):
            raise ValueError("latest_available_at must be timezone-aware")
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in self.source_available_at.values()
        ):
            raise ValueError("every source_available_at value must be timezone-aware")
        if self.history_sessions < 0 or self.estimated_order_notional_ntd <= ZERO:
            raise ValueError("history cannot be negative and order notional must be positive")
        object.__setattr__(self, "scope", QualityScope(self.scope))


@dataclass(frozen=True)
class DataQualityResult:
    passed: bool
    status: str
    completeness_score: float
    freshness: Freshness
    reason_codes: tuple[str, ...]
    source_dates: Mapping[str, date]
    latest_available_at: datetime | None
    adv_participation: Decimal | None
    hard_fail: bool


def evaluate_data_quality(
    data: DataQualityInput,
    config: DataQualityConfig | None = None,
) -> DataQualityResult:
    """Return a deterministic audit result; any hard reason blocks recommendation."""

    config = config or DataQualityConfig()
    require_production_horizon(data.horizon)
    reasons: list[str] = []
    security = data.security

    if security.asset_type != AssetType.COMMON_STOCK:
        reasons.append("ETF_EXCLUDED_FROM_STOCK_MODEL")
    if security.trading_status == TradingStatus.UNKNOWN:
        reasons.append("TRADING_STATUS_UNKNOWN")
    elif security.trading_status == TradingStatus.SUSPENDED:
        reasons.append("TRADING_SUSPENDED")
    elif security.trading_status == TradingStatus.STOPPED:
        reasons.append("TRADING_STOPPED")
    elif security.trading_status == TradingStatus.DELISTED:
        reasons.append("SECURITY_DELISTED")
    if security.attention_flag is None:
        reasons.append("ATTENTION_STATUS_UNKNOWN")
    if security.disposition_flag is None:
        reasons.append("DISPOSITION_STATUS_UNKNOWN")
    elif security.disposition_flag:
        reasons.append("DISPOSITION_SECURITY")
    if security.altered_trading_method_flag is None:
        reasons.append("ALTERED_TRADING_METHOD_STATUS_UNKNOWN")
    elif security.altered_trading_method_flag:
        reasons.append("ALTERED_TRADING_METHOD")
    if security.full_delivery_flag is None:
        reasons.append("FULL_DELIVERY_STATUS_UNKNOWN")
    elif security.full_delivery_flag:
        reasons.append("FULL_DELIVERY_SECURITY")
    if security.periodic_auction_flag is None:
        reasons.append("PERIODIC_AUCTION_STATUS_UNKNOWN")
    elif security.periodic_auction_flag:
        reasons.append("PERIODIC_AUCTION_SECURITY")
    if security.suspended_flag is None:
        reasons.append("SUSPENSION_STATUS_UNKNOWN")
    if security.attention_flag and config.exclude_attention:
        reasons.append("ATTENTION_SECURITY_EXCLUDED")

    if not data.has_corporate_action_data:
        reasons.append("CORPORATE_ACTION_DATA_MISSING")
    # Entry and exit are future outcomes at decision time. They are only
    # audited while creating labels or replaying executions, never as live
    # inference features.
    if data.scope is QualityScope.LABEL:
        if not data.has_executable_entry_price:
            reasons.append("EXECUTABLE_ENTRY_PRICE_MISSING")
        if not data.has_executable_exit_price:
            reasons.append("EXECUTABLE_EXIT_PRICE_MISSING")
    if data.history_sessions < config.minimum_history_sessions:
        reasons.append("INSUFFICIENT_LISTING_HISTORY")

    expected = set(data.expected_fields)
    present = set(data.present_fields)
    critical_missing = sorted(set(data.critical_fields).difference(present))
    reasons.extend(f"CRITICAL_FEATURE_MISSING:{field}" for field in critical_missing)
    completeness = len(expected.intersection(present)) / len(expected) if expected else 1.0

    adv_participation: Decimal | None = None
    if data.adv20_ntd is None or data.adv20_ntd <= ZERO:
        reasons.append("ADV20_MISSING")
    else:
        if data.adv20_ntd < config.minimum_adv20_ntd:
            reasons.append("LIQUIDITY_BELOW_MINIMUM")
        adv_participation = data.estimated_order_notional_ntd / data.adv20_ntd
        if adv_participation > config.max_adv_participation:
            reasons.append("CAPACITY_LIMIT_EXCEEDED")

    if data.source_available_at:
        future_sources = sorted(
            name for name, value in data.source_available_at.items() if value > data.decision_at
        )
        stale_sources = sorted(
            name
            for name, value in data.source_available_at.items()
            if value <= data.decision_at
            and data.decision_at - value > config.maximum_source_age
        )
        reasons.extend(f"LOOKAHEAD_TIMESTAMP:{name}" for name in future_sources)
        reasons.extend(f"STALE_SOURCE_DATA:{name}" for name in stale_sources)
        freshness = Freshness.STALE if future_sources or stale_sources else Freshness.FRESH
    elif data.latest_available_at is None:
        freshness = Freshness.MISSING
        reasons.append("LATEST_AVAILABLE_AT_MISSING")
    elif data.latest_available_at > data.decision_at:
        freshness = Freshness.STALE
        reasons.append("LOOKAHEAD_TIMESTAMP")
    elif data.decision_at - data.latest_available_at > config.maximum_source_age:
        freshness = Freshness.STALE
        reasons.append("STALE_SOURCE_DATA")
    else:
        freshness = Freshness.FRESH

    unique_reasons = tuple(dict.fromkeys(reasons))
    hard_fail = bool(unique_reasons)
    return DataQualityResult(
        passed=not hard_fail,
        status="PASS" if not hard_fail else "FAIL",
        completeness_score=completeness,
        freshness=freshness,
        reason_codes=unique_reasons,
        source_dates=dict(data.source_dates),
        latest_available_at=data.latest_available_at,
        adv_participation=adv_participation,
        hard_fail=hard_fail,
    )
