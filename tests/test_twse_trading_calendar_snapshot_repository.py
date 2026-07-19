from __future__ import annotations

from datetime import date
from typing import cast

import pytest

from src.data.ingestion.supabase_writer import SupabaseWriter
from src.data.research.twse_trading_calendar_snapshot import (
    TradingCalendarSnapshotError,
)
from src.data.research.twse_trading_calendar_snapshot_repository import (
    TwseTradingCalendarObservationRepository,
    build_twse_trading_calendar_snapshot,
)


def _row(trading_date: str) -> dict[str, object]:
    digest = "a" * 64
    return {
        "market": "TWSE",
        "trading_date": trading_date,
        "is_trading_day": True,
        "source_version": "finmind-calendar-v1",
        "source_revision_hash": digest,
        "source_payload_hash": "b" * 64,
        "first_observed_at": "2026-07-19T00:00:00+00:00",
        "available_at": "2026-07-19T00:00:00+00:00",
        "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
        "calendar_verification_status": "UNRESOLVED",
        "market_basis": "SCHEDULING_HINT",
        "usage_scope": "CALENDAR_RESEARCH_ONLY",
        "system_status": "RESEARCH_ONLY",
        "reason_codes": ["RESEARCH_SCHEDULING_HINT"],
    }


class _Source:
    def __init__(self) -> None:
        self.offsets: list[str] = []

    def select_rows(self, _table: str, **kwargs: object) -> list[dict[str, object]]:
        filters = cast(dict[str, str], kwargs["filters"])
        self.offsets.append(filters["offset"])
        return [_row("2026-07-01")] if filters["offset"] == "0" else []


def test_repository_pages_calendar_observations() -> None:
    source = _Source()
    rows = TwseTradingCalendarObservationRepository(
        cast(SupabaseWriter, source), page_size=1
    ).fetch(start_date=date(2026, 7, 1), end_date=date(2026, 7, 31))

    assert len(rows) == 1
    assert source.offsets == ["0", "1"]


def test_snapshot_builder_orders_sessions_and_hashes_content() -> None:
    snapshot = build_twse_trading_calendar_snapshot(
        [_row("2026-07-02"), _row("2026-07-01")]
    )

    assert snapshot.session_dates == (date(2026, 7, 1), date(2026, 7, 2))
    assert len(snapshot.calendar_snapshot_sha256) == 64


def test_snapshot_builder_rejects_duplicate_dates() -> None:
    with pytest.raises(TradingCalendarSnapshotError) as captured:
        _ = build_twse_trading_calendar_snapshot(
            [_row("2026-07-01"), _row("2026-07-01")]
        )

    assert captured.value.reason_code == "TRADING_CALENDAR_SNAPSHOT_MISMATCH"
