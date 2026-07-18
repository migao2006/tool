"""Contracts for point-in-time security identity and benchmark assignments."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class Market(str, Enum):
    TWSE = "TWSE"
    TPEX = "TPEX"
    # Backward-compatible aliases; persistence and API output use TWSE/TPEX.
    LISTED = "TWSE"
    OTC = "TPEX"
    ETF = "ETF"


class AssetType(str, Enum):
    COMMON_STOCK = "COMMON_STOCK"
    ETF = "ETF"


class TradingStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    STOPPED = "STOPPED"
    DELISTED = "DELISTED"


@dataclass(frozen=True, kw_only=True)
class SecurityRecord:
    """One effective-dated, release-timestamped security-master version."""

    security_id: int
    listing_period_id: str
    symbol: str
    name: str
    market: Market
    industry: str
    asset_type: AssetType
    valid_from: date
    available_at: datetime
    first_observed_at: datetime
    available_at_basis: str
    point_in_time_status: str
    usage_scope: str
    reason_codes: tuple[str, ...]
    source_id: int
    source_version: str
    source_revision_hash: str
    valid_to: date | None = None
    listing_date: date | None = None
    delisting_date: date | None = None
    trading_status: TradingStatus = TradingStatus.UNKNOWN
    attention_flag: bool | None = None
    disposition_flag: bool | None = None
    altered_trading_method_flag: bool | None = None
    full_delivery_flag: bool | None = None
    periodic_auction_flag: bool | None = None
    suspended_flag: bool | None = None

    def __post_init__(self) -> None:
        if self.security_id < 1 or self.source_id < 1:
            raise ValueError("security_id and source_id must be positive")
        if not self.listing_period_id.strip():
            raise ValueError("listing_period_id is required")
        if not self.symbol.strip() or not self.name.strip():
            raise ValueError("security symbol and name are required")
        if not self.source_version.strip():
            raise ValueError("security source_version is required")
        require_aware(self.available_at, "security available_at")
        require_aware(self.first_observed_at, "security first_observed_at")
        if self.available_at_basis not in {
            "OFFICIAL_PUBLICATION_AT",
            "VERSIONED_SNAPSHOT",
            "FIRST_OBSERVED_AT_RETRIEVAL",
        }:
            raise ValueError("unsupported security available_at_basis")
        if self.available_at_basis == "OFFICIAL_PUBLICATION_AT":
            if self.available_at > self.first_observed_at:
                raise ValueError("security availability follows first observation")
        elif self.available_at != self.first_observed_at:
            raise ValueError(
                "security snapshot availability must equal first observation"
            )
        if self.point_in_time_status not in {"VERIFIED", "UNVERIFIED"}:
            raise ValueError("unsupported security point_in_time_status")
        if self.usage_scope not in {
            "POINT_IN_TIME_IDENTITY",
            "IDENTITY_RESEARCH_ONLY",
        }:
            raise ValueError("unsupported security usage_scope")
        if self.point_in_time_status == "VERIFIED":
            if (
                self.available_at_basis == "FIRST_OBSERVED_AT_RETRIEVAL"
                or self.usage_scope != "POINT_IN_TIME_IDENTITY"
                or self.reason_codes
            ):
                raise ValueError("verified security identity exceeds its evidence")
        elif self.usage_scope != "IDENTITY_RESEARCH_ONLY" or not self.reason_codes:
            raise ValueError("unverified security identity requires research reasons")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        if self.listing_date is not None and self.valid_from < self.listing_date:
            raise ValueError("valid_from cannot precede listing_date")
        if (
            self.delisting_date is not None
            and self.listing_date is not None
            and self.delisting_date < self.listing_date
        ):
            raise ValueError("delisting_date cannot precede listing_date")
        if not _SHA256_PATTERN.fullmatch(self.source_revision_hash):
            raise ValueError("source_revision_hash must be a lowercase SHA-256 digest")
        if self.asset_type == AssetType.ETF and self.market not in {
            Market.TWSE,
            Market.TPEX,
            Market.ETF,
        }:
            raise ValueError("ETF securities must retain their actual TWSE/TPEX venue")
        if self.asset_type == AssetType.COMMON_STOCK and self.market == Market.ETF:
            raise ValueError("common stock cannot use the ETF market partition")

    def effective_on(self, as_of_date: date) -> bool:
        return self.valid_from <= as_of_date and (
            self.valid_to is None or as_of_date < self.valid_to
        )

    def available_for(self, as_of_date: date, decision_at: datetime) -> bool:
        require_aware(decision_at, "decision_at")
        return (
            self.effective_on(as_of_date)
            and self.available_at <= decision_at
            and self.point_in_time_status == "VERIFIED"
            and self.usage_scope == "POINT_IN_TIME_IDENTITY"
        )


@dataclass(frozen=True)
class BenchmarkAssignment:
    market: Market
    benchmark_id: str
    version: str
    valid_from: date
    available_at: datetime
    valid_to: date | None = None

    def __post_init__(self) -> None:
        if not self.benchmark_id or not self.version:
            raise ValueError("benchmark id and version are required")
        require_aware(self.available_at, "benchmark available_at")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("benchmark valid_to must be later than valid_from")

    def effective_on(self, as_of_date: date) -> bool:
        return self.valid_from <= as_of_date and (
            self.valid_to is None or as_of_date < self.valid_to
        )

    def available_for(self, as_of_date: date, decision_at: datetime) -> bool:
        return self.effective_on(as_of_date) and self.available_at <= decision_at


@dataclass(frozen=True)
class UniverseSnapshot:
    as_of_date: date
    horizon: int
    securities: tuple[SecurityRecord, ...]
    benchmark_version_by_market: dict[Market, tuple[str, str]]
