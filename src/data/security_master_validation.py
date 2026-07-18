"""Cross-record integrity rules for point-in-time security-master data."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from datetime import date, datetime

from .security_master_contracts import (
    AssetType,
    BenchmarkAssignment,
    Market,
    SecurityRecord,
)


def validate_identity_consistency(records: tuple[SecurityRecord, ...]) -> None:
    security_asset_type: dict[int, AssetType] = {}
    listing_identity: dict[str, tuple[int, Market, str, AssetType]] = {}
    for record in records:
        existing_asset_type = security_asset_type.setdefault(
            record.security_id,
            record.asset_type,
        )
        if existing_asset_type != record.asset_type:
            raise ValueError(
                f"security_id={record.security_id} maps to multiple asset types"
            )
        by_listing = (
            record.security_id,
            record.market,
            record.symbol,
            record.asset_type,
        )
        existing_listing = listing_identity.setdefault(
            record.listing_period_id, by_listing
        )
        if existing_listing != by_listing:
            raise ValueError(
                f"listing_period_id={record.listing_period_id} maps to multiple securities"
            )


def validate_non_overlapping_records(records: tuple[SecurityRecord, ...]) -> None:
    _validate_revision_slots(records)
    logical_intervals = _logical_intervals(records)
    _validate_interval_groups(
        logical_intervals,
        label="listing_period_id",
        key_function=lambda record: record.listing_period_id,
        ignore_same_listing_period=False,
    )
    _validate_interval_groups(
        logical_intervals,
        label="security_id",
        key_function=lambda record: record.security_id,
        ignore_same_listing_period=True,
    )
    _validate_interval_groups(
        logical_intervals,
        label="market_symbol",
        key_function=lambda record: (record.market, record.symbol),
        ignore_same_listing_period=True,
    )


def validate_non_overlapping_benchmarks(
    benchmarks: tuple[BenchmarkAssignment, ...],
) -> None:
    by_market: dict[Market, list[BenchmarkAssignment]] = {}
    for assignment in benchmarks:
        by_market.setdefault(assignment.market, []).append(assignment)
    for market, assignments in by_market.items():
        ordered = sorted(assignments, key=lambda assignment: assignment.valid_from)
        for previous, current in zip(ordered, ordered[1:]):
            if previous.valid_to is None or previous.valid_to > current.valid_from:
                raise ValueError(f"overlapping benchmark ranges for {market.value}")


def _validate_revision_slots(records: tuple[SecurityRecord, ...]) -> None:
    slots: dict[tuple[str, date, date | None, datetime], SecurityRecord] = {}
    for record in records:
        key = (
            record.listing_period_id,
            record.valid_from,
            record.valid_to,
            record.available_at,
        )
        existing = slots.get(key)
        if existing is None:
            slots[key] = record
            continue
        if existing != record:
            raise ValueError(
                "conflicting security-master revisions at the same available_at "
                + f"for listing_period_id={record.listing_period_id}"
            )


def _logical_intervals(
    records: tuple[SecurityRecord, ...],
) -> tuple[SecurityRecord, ...]:
    intervals: dict[tuple[str, date, date | None], SecurityRecord] = {}
    for record in records:
        key = (record.listing_period_id, record.valid_from, record.valid_to)
        if key not in intervals:
            intervals[key] = record
    return tuple(intervals.values())


def _validate_interval_groups(
    records: Iterable[SecurityRecord],
    *,
    label: str,
    key_function: Callable[[SecurityRecord], Hashable],
    ignore_same_listing_period: bool,
) -> None:
    grouped: dict[Hashable, list[SecurityRecord]] = {}
    for record in records:
        grouped.setdefault(key_function(record), []).append(record)
    for identity, group in grouped.items():
        ordered = sorted(group, key=lambda record: record.valid_from)
        for index, previous in enumerate(ordered):
            for current in ordered[index + 1 :]:
                if (
                    ignore_same_listing_period
                    and previous.listing_period_id == current.listing_period_id
                ):
                    continue
                if (
                    previous.valid_to is not None
                    and previous.valid_to <= current.valid_from
                ):
                    break
                raise ValueError(
                    f"overlapping security-master ranges for {label}={identity}"
                )
