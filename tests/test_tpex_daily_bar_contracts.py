from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from src.data.research.tpex_daily_bar_contracts import (
    TpexDailyBar,
    TpexDailyBarRevision,
    TpexDailyBarSeriesSnapshot,
    daily_bar_revision_hash,
    daily_bar_series_hash,
)


AS_OF_DATE = date(2026, 7, 20)
SOURCE_ID = 7


def _bar(
    *,
    daily_bar_id: int = 1,
    security_id: int = 101,
    trade_date: date = AS_OF_DATE,
    source_version: str = "revision-a",
    available_at: datetime | None = None,
) -> TpexDailyBar:
    return TpexDailyBar(
        daily_bar_id=daily_bar_id,
        security_id=security_id,
        trade_date=trade_date,
        open_price=10.0,
        high_price=11.0,
        low_price=9.5,
        close_price=10.5,
        trading_volume=1_000.0,
        trading_value=10_500.0,
        source_id=SOURCE_ID,
        source_version=source_version,
        available_at=available_at or datetime(2026, 7, 20, 10, tzinfo=timezone.utc),
    )


def _revision(*rows: TpexDailyBar) -> TpexDailyBarRevision:
    ordered = tuple(sorted(rows, key=lambda row: row.security_id))
    return TpexDailyBarRevision(
        as_of_date=AS_OF_DATE,
        source_id=SOURCE_ID,
        source_version=ordered[0].source_version,
        rows=ordered,
        snapshot_sha256=daily_bar_revision_hash(
            as_of_date=AS_OF_DATE,
            source_id=SOURCE_ID,
            source_version=ordered[0].source_version,
            rows=ordered,
        ),
    )


def test_daily_bar_hashes_are_deterministic_and_cover_meaningful_values() -> None:
    taipei_time = datetime(
        2026,
        7,
        20,
        18,
        tzinfo=timezone(timedelta(hours=8)),
    )
    first = _bar(available_at=taipei_time)
    equivalent = _bar(available_at=taipei_time.astimezone(timezone.utc))
    changed = replace(first, trading_value=10_501.0)

    first_hash = daily_bar_revision_hash(
        as_of_date=AS_OF_DATE,
        source_id=SOURCE_ID,
        source_version="revision-a",
        rows=(first,),
    )
    equivalent_hash = daily_bar_revision_hash(
        as_of_date=AS_OF_DATE,
        source_id=SOURCE_ID,
        source_version="revision-a",
        rows=(equivalent,),
    )
    changed_hash = daily_bar_revision_hash(
        as_of_date=AS_OF_DATE,
        source_id=SOURCE_ID,
        source_version="revision-a",
        rows=(changed,),
    )

    assert first.available_at == datetime(2026, 7, 20, 10, tzinfo=timezone.utc)
    assert first_hash == equivalent_hash
    assert first_hash != changed_hash

    revision = _revision(first)
    series_hash = daily_bar_series_hash((revision,))
    assert series_hash == daily_bar_series_hash((revision,))
    assert (
        TpexDailyBarSeriesSnapshot(
            revisions=(revision,),
            snapshot_sha256=series_hash,
        ).row_count
        == 1
    )


def test_daily_bar_contracts_reject_hash_and_row_order_tampering() -> None:
    first = _bar(daily_bar_id=1, security_id=101)
    second = _bar(daily_bar_id=2, security_id=102)
    revision = _revision(first, second)

    with pytest.raises(ValueError, match="does not match its rows"):
        replace(revision, snapshot_sha256="0" * 64)
    with pytest.raises(ValueError, match="security-id sorted"):
        replace(revision, rows=(second, first))

    series = TpexDailyBarSeriesSnapshot(
        revisions=(revision,),
        snapshot_sha256=daily_bar_series_hash((revision,)),
    )
    with pytest.raises(ValueError, match="does not match revisions"):
        replace(series, snapshot_sha256="0" * 64)
