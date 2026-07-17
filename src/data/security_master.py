"""Point-in-time security universe and benchmark assignments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Iterable

from src.core.horizon import PRODUCTION_HORIZON, require_production_horizon


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
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    STOPPED = "STOPPED"
    DELISTED = "DELISTED"


@dataclass(frozen=True)
class SecurityRecord:
    """One effective-dated version of a security's identity and trading state."""

    symbol: str
    name: str
    market: Market
    industry: str
    asset_type: AssetType
    valid_from: date
    valid_to: date | None = None
    listing_date: date | None = None
    delisting_date: date | None = None
    trading_status: TradingStatus = TradingStatus.ACTIVE
    attention_flag: bool = False
    disposition_flag: bool = False
    altered_trading_method_flag: bool = False
    full_delivery_flag: bool = False
    periodic_auction_flag: bool = False

    def __post_init__(self) -> None:
        if not self.symbol or not self.name:
            raise ValueError("security symbol and name are required")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        if self.asset_type == AssetType.ETF and self.market not in {Market.TWSE, Market.TPEX, Market.ETF}:
            raise ValueError("ETF securities must retain their actual TWSE/TPEX venue")
        if self.asset_type == AssetType.COMMON_STOCK and self.market == Market.ETF:
            raise ValueError("common stock cannot use the ETF market partition")

    def effective_on(self, as_of_date: date) -> bool:
        return self.valid_from <= as_of_date and (
            self.valid_to is None or as_of_date < self.valid_to
        )


@dataclass(frozen=True)
class BenchmarkAssignment:
    market: Market
    benchmark_id: str
    version: str
    valid_from: date
    valid_to: date | None = None

    def __post_init__(self) -> None:
        if not self.benchmark_id or not self.version:
            raise ValueError("benchmark id and version are required")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("benchmark valid_to must be later than valid_from")

    def effective_on(self, as_of_date: date) -> bool:
        return self.valid_from <= as_of_date and (
            self.valid_to is None or as_of_date < self.valid_to
        )


@dataclass(frozen=True)
class UniverseSnapshot:
    as_of_date: date
    horizon: int
    securities: tuple[SecurityRecord, ...]
    benchmark_version_by_market: dict[Market, tuple[str, str]]


class SecurityMaster:
    """Resolve historical constituents without using today's surviving universe."""

    def __init__(
        self,
        records: Iterable[SecurityRecord],
        benchmarks: Iterable[BenchmarkAssignment],
    ) -> None:
        self._records = tuple(records)
        self._benchmarks = tuple(benchmarks)
        self._validate_non_overlapping_records()
        self._validate_non_overlapping_benchmarks()

    def record_for(self, symbol: str, as_of_date: date) -> SecurityRecord | None:
        matches = [
            record
            for record in self._records
            if record.symbol == symbol and record.effective_on(as_of_date)
        ]
        if len(matches) > 1:
            raise ValueError(f"overlapping security-master versions for {symbol}")
        return matches[0] if matches else None

    def benchmark_for(self, market: Market, as_of_date: date) -> BenchmarkAssignment:
        matches = [
            assignment
            for assignment in self._benchmarks
            if assignment.market == market and assignment.effective_on(as_of_date)
        ]
        if len(matches) != 1:
            raise ValueError(
                f"expected one benchmark for market={market.value} at {as_of_date}, got {len(matches)}"
            )
        return matches[0]

    def common_stock_universe(
        self,
        as_of_date: date,
        *,
        horizon: int = PRODUCTION_HORIZON,
        include_non_active: bool = True,
    ) -> UniverseSnapshot:
        require_production_horizon(horizon)
        candidates = [
            record
            for record in self._records
            if record.effective_on(as_of_date)
            and record.asset_type == AssetType.COMMON_STOCK
            and record.market in {Market.LISTED, Market.OTC}
            and (include_non_active or record.trading_status == TradingStatus.ACTIVE)
        ]
        # Preserve delisted/suspended records in historical snapshots; quality gates,
        # not survivorship-filtered universe construction, decide recommendation use.
        candidates.sort(key=lambda record: (record.market.value, record.symbol))
        versions: dict[Market, tuple[str, str]] = {}
        for market in {record.market for record in candidates}:
            assignment = self.benchmark_for(market, as_of_date)
            versions[market] = (assignment.benchmark_id, assignment.version)
        return UniverseSnapshot(
            as_of_date=as_of_date,
            horizon=horizon,
            securities=tuple(candidates),
            benchmark_version_by_market=versions,
        )

    def _validate_non_overlapping_records(self) -> None:
        by_symbol: dict[str, list[SecurityRecord]] = {}
        for record in self._records:
            by_symbol.setdefault(record.symbol, []).append(record)
        for symbol, records in by_symbol.items():
            ordered = sorted(records, key=lambda record: record.valid_from)
            for previous, current in zip(ordered, ordered[1:]):
                if previous.valid_to is None or previous.valid_to > current.valid_from:
                    raise ValueError(f"overlapping security-master ranges for {symbol}")

    def _validate_non_overlapping_benchmarks(self) -> None:
        by_market: dict[Market, list[BenchmarkAssignment]] = {}
        for assignment in self._benchmarks:
            by_market.setdefault(assignment.market, []).append(assignment)
        for market, assignments in by_market.items():
            ordered = sorted(assignments, key=lambda assignment: assignment.valid_from)
            for previous, current in zip(ordered, ordered[1:]):
                if previous.valid_to is None or previous.valid_to > current.valid_from:
                    raise ValueError(f"overlapping benchmark ranges for {market.value}")
