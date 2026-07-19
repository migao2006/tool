"""Read and build versioned TWSE research calendar snapshots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from src.data.ingestion.supabase_writer import SupabaseWriter

from .twse_trading_calendar_snapshot import (
    TradingCalendarSnapshotError,
    TwseTradingCalendarSession,
    TwseTradingCalendarSnapshot,
    calendar_snapshot_hash,
)


CALENDAR_SELECT = ",".join(
    (
        "market",
        "trading_date",
        "is_trading_day",
        "source_version",
        "source_revision_hash",
        "source_payload_hash",
        "first_observed_at",
        "available_at",
        "available_at_basis",
        "calendar_verification_status",
        "market_basis",
        "usage_scope",
        "system_status",
        "reason_codes",
    )
)


class TwseTradingCalendarObservationRepository:
    """Page through private calendar observations in deterministic order."""

    def __init__(self, source: SupabaseWriter, *, page_size: int = 1_000) -> None:
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        self.source: SupabaseWriter = source
        self.page_size: int = page_size

    def fetch(self, *, start_date: date, end_date: date) -> list[dict[str, object]]:
        if end_date < start_date:
            raise ValueError("end_date must not precede start_date")
        rows: list[dict[str, object]] = []
        offset = 0
        while True:
            page = self.source.select_rows(
                "trading_calendar_observations",
                select=CALENDAR_SELECT,
                filters={
                    "market": "eq.TWSE",
                    "is_trading_day": "eq.true",
                    "and": (
                        f"(trading_date.gte.{start_date.isoformat()},"
                        f"trading_date.lte.{end_date.isoformat()})"
                    ),
                    "order": "trading_date.asc,first_observed_at.asc",
                    "offset": str(offset),
                },
                limit=self.page_size,
            )
            rows.extend(page)
            if len(page) < self.page_size:
                return rows
            offset += len(page)


def build_twse_trading_calendar_snapshot(
    rows: Sequence[Mapping[str, object]],
) -> TwseTradingCalendarSnapshot:
    """Build a fail-closed snapshot without inventing missing sessions."""

    sessions = tuple(TwseTradingCalendarSession.from_mapping(row) for row in rows)
    dates = tuple(session.trading_date for session in sessions)
    if len(dates) != len(set(dates)):
        raise TradingCalendarSnapshotError(
            "Trading-calendar observations contain duplicate trading dates"
        )
    ordered = tuple(sorted(sessions, key=lambda session: session.trading_date))
    try:
        return TwseTradingCalendarSnapshot(
            sessions=ordered,
            calendar_snapshot_sha256=calendar_snapshot_hash(ordered),
        )
    except ValueError as error:
        raise TradingCalendarSnapshotError(
            "Unable to build a valid trading-calendar snapshot"
        ) from error


__all__ = [
    "CALENDAR_SELECT",
    "TwseTradingCalendarObservationRepository",
    "build_twse_trading_calendar_snapshot",
]
