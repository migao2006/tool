from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from typing import final

import pytest

from src.data.research.tpex_daily_bar_repository import (
    TpexDailyBarRepository,
    TpexDailyBarSourceError,
)


AS_OF_DATE = date(2026, 7, 20)
SOURCE_ID = 7


def _raw_row(
    *,
    daily_bar_id: int,
    security_id: int,
    trade_date: date = AS_OF_DATE,
    source_version: str = "revision-a",
    available_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "daily_bar_id": daily_bar_id,
        "security_id": security_id,
        "trade_date": trade_date.isoformat(),
        "raw_open": "10.0",
        "raw_high": "11.0",
        "raw_low": "9.5",
        "raw_close": "10.5",
        "volume_shares": "1000",
        "turnover_ntd": "10500",
        "source_id": SOURCE_ID,
        "source_version": source_version,
        "available_at": (
            available_at or datetime(2026, 7, 20, 10, tzinfo=timezone.utc)
        ).isoformat(),
    }


@final
class FakeDailyBarSource:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, Mapping[str, str], int]] = []

    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]:
        normalized = dict(filters or {})
        self.calls.append((table, normalized, limit))
        if table == "data_sources":
            assert select == "source_id,source_code"
            return [{"source_id": SOURCE_ID, "source_code": "TPEX"}]

        assert table == "daily_bars"
        source_id = int(normalized["source_id"].removeprefix("eq."))
        start_date = date.fromisoformat(normalized["trade_date"].removeprefix("gte."))
        eligible = [
            row
            for row in self.rows
            if int(str(row["source_id"])) == source_id
            and date.fromisoformat(str(row["trade_date"])) >= start_date
        ]
        if select == "daily_bar_id":
            eligible.sort(key=lambda row: int(str(row["daily_bar_id"])), reverse=True)
            return [{"daily_bar_id": row["daily_bar_id"]} for row in eligible[:limit]]
        assert "source_version" in select
        last_id = int(normalized["daily_bar_id"].removeprefix("gt."))
        selected = [row for row in eligible if int(str(row["daily_bar_id"])) > last_id]
        selected.sort(key=lambda row: int(str(row["daily_bar_id"])))
        return selected[:limit]


def test_repository_selects_latest_revision_and_freezes_a_stable_snapshot() -> None:
    earlier = datetime(2026, 7, 20, 9, tzinfo=timezone.utc)
    later = datetime(2026, 7, 20, 10, tzinfo=timezone.utc)
    source = FakeDailyBarSource(
        [
            _raw_row(
                daily_bar_id=1,
                security_id=101,
                source_version="revision-a",
                available_at=earlier,
            ),
            _raw_row(
                daily_bar_id=2,
                security_id=102,
                source_version="revision-a",
                available_at=earlier,
            ),
            _raw_row(
                daily_bar_id=3,
                security_id=102,
                source_version="revision-b",
                available_at=later,
            ),
            _raw_row(
                daily_bar_id=4,
                security_id=101,
                source_version="revision-b",
                available_at=later,
            ),
        ]
    )

    first = TpexDailyBarRepository(
        source,
        page_size=2,
        minimum_rows=2,
    ).fetch_range(start_date=AS_OF_DATE, as_of_date=AS_OF_DATE)
    second = TpexDailyBarRepository(
        source,
        page_size=3,
        minimum_rows=2,
    ).fetch_range(start_date=AS_OF_DATE, as_of_date=AS_OF_DATE)

    assert first == second
    assert first.snapshot_sha256 == second.snapshot_sha256
    assert first.revisions[0].source_version == "revision-b"
    assert [row.security_id for row in first.revisions[0].rows] == [101, 102]
    assert [row.daily_bar_id for row in first.revisions[0].rows] == [4, 3]


def test_repository_uses_source_version_as_a_deterministic_revision_tiebreak() -> None:
    observed_at = datetime(2026, 7, 20, 10, tzinfo=timezone.utc)
    source = FakeDailyBarSource(
        [
            _raw_row(
                daily_bar_id=1,
                security_id=101,
                source_version="revision-a",
                available_at=observed_at,
            ),
            _raw_row(
                daily_bar_id=2,
                security_id=102,
                source_version="revision-a",
                available_at=observed_at,
            ),
            _raw_row(
                daily_bar_id=3,
                security_id=101,
                source_version="revision-b",
                available_at=observed_at,
            ),
            _raw_row(
                daily_bar_id=4,
                security_id=102,
                source_version="revision-b",
                available_at=observed_at,
            ),
        ]
    )

    snapshot = TpexDailyBarRepository(source, minimum_rows=2).fetch_range(
        start_date=AS_OF_DATE,
        as_of_date=AS_OF_DATE,
    )

    assert snapshot.revisions[0].source_version == "revision-b"


def test_repository_rejects_incomplete_newest_revision_instead_of_falling_back() -> (
    None
):
    earlier = datetime(2026, 7, 20, 9, tzinfo=timezone.utc)
    later = datetime(2026, 7, 20, 10, tzinfo=timezone.utc)
    source = FakeDailyBarSource(
        [
            _raw_row(
                daily_bar_id=1,
                security_id=101,
                source_version="complete-old",
                available_at=earlier,
            ),
            _raw_row(
                daily_bar_id=2,
                security_id=102,
                source_version="complete-old",
                available_at=earlier,
            ),
            _raw_row(
                daily_bar_id=3,
                security_id=101,
                source_version="incomplete-new",
                available_at=later,
            ),
        ]
    )

    with pytest.raises(TpexDailyBarSourceError) as captured:
        TpexDailyBarRepository(source, minimum_rows=2).fetch_range(
            start_date=AS_OF_DATE,
            as_of_date=AS_OF_DATE,
        )

    assert captured.value.reason_code == "TPEX_DAILY_BAR_CROSS_SECTION_INCOMPLETE"


def test_repository_requires_the_exact_requested_as_of_date() -> None:
    source = FakeDailyBarSource(
        [
            _raw_row(daily_bar_id=1, security_id=101),
            _raw_row(daily_bar_id=2, security_id=102),
        ]
    )

    with pytest.raises(TpexDailyBarSourceError) as captured:
        TpexDailyBarRepository(source, minimum_rows=2).fetch_range(
            start_date=AS_OF_DATE,
            as_of_date=AS_OF_DATE + timedelta(days=1),
        )

    assert captured.value.reason_code == "TPEX_DAILY_BAR_AS_OF_DATE_UNAVAILABLE"


def test_repository_rejects_duplicate_security_within_one_revision() -> None:
    source = FakeDailyBarSource(
        [
            _raw_row(daily_bar_id=1, security_id=101),
            _raw_row(daily_bar_id=2, security_id=101),
        ]
    )

    with pytest.raises(TpexDailyBarSourceError) as captured:
        TpexDailyBarRepository(source, minimum_rows=2).fetch_range(
            start_date=AS_OF_DATE,
            as_of_date=AS_OF_DATE,
        )

    assert captured.value.reason_code == "TPEX_DAILY_BAR_SECURITY_DUPLICATE"


def test_repository_ignores_rows_appended_after_the_frozen_high_water() -> None:
    source = FakeDailyBarSource(
        [
            _raw_row(daily_bar_id=1, security_id=101),
            _raw_row(daily_bar_id=2, security_id=102),
        ]
    )
    original_select = source.select_rows

    def select_with_concurrent_append(
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]:
        rows = original_select(
            table,
            select=select,
            filters=filters,
            limit=limit,
        )
        if table == "daily_bars" and select == "daily_bar_id":
            source.rows.append(_raw_row(daily_bar_id=3, security_id=103))
        return rows

    source.select_rows = select_with_concurrent_append  # type: ignore[method-assign]

    snapshot = TpexDailyBarRepository(source, minimum_rows=2).fetch_range(
        start_date=AS_OF_DATE,
        as_of_date=AS_OF_DATE,
    )

    assert [row.daily_bar_id for row in snapshot.revisions[0].rows] == [1, 2]
