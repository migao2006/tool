"""Point-in-time security universe and benchmark assignment queries."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import final

from src.core.horizon import PRODUCTION_HORIZON, require_production_horizon

from .security_master_contracts import (
    AssetType,
    BenchmarkAssignment,
    Market,
    SecurityRecord,
    TradingStatus,
    UniverseSnapshot,
    require_aware,
)
from .security_master_validation import (
    validate_identity_consistency,
    validate_non_overlapping_benchmarks,
    validate_non_overlapping_records,
)


@final
class SecurityMaster:
    """Resolve historical constituents without using today's surviving universe."""

    def __init__(
        self,
        records: Iterable[SecurityRecord],
        benchmarks: Iterable[BenchmarkAssignment],
    ) -> None:
        self._records: tuple[SecurityRecord, ...] = tuple(records)
        self._benchmarks: tuple[BenchmarkAssignment, ...] = tuple(benchmarks)
        validate_identity_consistency(self._records)
        validate_non_overlapping_records(self._records)
        validate_non_overlapping_benchmarks(self._benchmarks)

    def record_for_security_id(
        self,
        security_id: int,
        as_of_date: date,
        *,
        decision_at: datetime,
    ) -> SecurityRecord | None:
        return self._one_available_record(
            (
                record
                for record in self._records
                if record.security_id == security_id
                and record.available_for(as_of_date, decision_at)
            ),
            identity=f"security_id={security_id}",
        )

    def record_for_listing_period(
        self,
        listing_period_id: str,
        as_of_date: date,
        *,
        decision_at: datetime,
    ) -> SecurityRecord | None:
        return self._one_available_record(
            (
                record
                for record in self._records
                if record.listing_period_id == listing_period_id
                and record.available_for(as_of_date, decision_at)
            ),
            identity=f"listing_period_id={listing_period_id}",
        )

    def record_for_market_symbol(
        self,
        market: Market,
        symbol: str,
        as_of_date: date,
        *,
        decision_at: datetime,
    ) -> SecurityRecord | None:
        """Resolve a ticker only when its venue and point-in-time are explicit."""

        return self._one_available_record(
            (
                record
                for record in self._records
                if record.market == market
                and record.symbol == symbol
                and record.available_for(as_of_date, decision_at)
            ),
            identity=f"market={market.value},symbol={symbol}",
        )

    @staticmethod
    def _one_available_record(
        records: Iterable[SecurityRecord],
        *,
        identity: str,
    ) -> SecurityRecord | None:
        matches = tuple(records)
        if not matches:
            return None
        latest_available_at = max(record.available_at for record in matches)
        latest = tuple(
            record for record in matches if record.available_at == latest_available_at
        )
        reference = latest[0]
        if any(record != reference for record in latest[1:]):
            raise ValueError(
                "conflicting security-master revisions at the same available_at "
                + f"for {identity}"
            )
        return reference

    def benchmark_for(
        self,
        market: Market,
        as_of_date: date,
        *,
        decision_at: datetime,
    ) -> BenchmarkAssignment:
        require_aware(decision_at, "decision_at")
        matches = [
            assignment
            for assignment in self._benchmarks
            if assignment.market == market
            and assignment.available_for(as_of_date, decision_at)
        ]
        if len(matches) != 1:
            message = f"expected one benchmark for market={market.value}"
            message += f" at {as_of_date}, got {len(matches)}"
            raise ValueError(message)
        return matches[0]

    def common_stock_universe(
        self,
        as_of_date: date,
        *,
        decision_at: datetime,
        horizon: int = PRODUCTION_HORIZON,
        include_non_active: bool = True,
    ) -> UniverseSnapshot:
        require_aware(decision_at, "decision_at")
        _ = require_production_horizon(horizon)
        candidates: list[SecurityRecord] = []
        for listing_period_id in dict.fromkeys(
            record.listing_period_id for record in self._records
        ):
            record = self.record_for_listing_period(
                listing_period_id,
                as_of_date,
                decision_at=decision_at,
            )
            if record is None or record.asset_type != AssetType.COMMON_STOCK:
                continue
            if record.market not in {Market.LISTED, Market.OTC}:
                continue
            if not include_non_active and record.trading_status != TradingStatus.ACTIVE:
                continue
            candidates.append(record)

        candidates.sort(
            key=lambda record: (
                record.market.value,
                record.symbol,
                record.listing_period_id,
            )
        )
        versions: dict[Market, tuple[str, str]] = {}
        for market in {record.market for record in candidates}:
            assignment = self.benchmark_for(
                market,
                as_of_date,
                decision_at=decision_at,
            )
            versions[market] = (assignment.benchmark_id, assignment.version)
        return UniverseSnapshot(
            as_of_date=as_of_date,
            horizon=horizon,
            securities=tuple(candidates),
            benchmark_version_by_market=versions,
        )


__all__ = [
    "AssetType",
    "BenchmarkAssignment",
    "Market",
    "SecurityMaster",
    "SecurityRecord",
    "TradingStatus",
    "UniverseSnapshot",
]
