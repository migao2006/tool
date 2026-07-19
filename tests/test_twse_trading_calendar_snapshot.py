from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path

import pytest

from src.data.research.twse_trading_calendar_snapshot import (
    TradingCalendarSnapshotError,
    TwseTradingCalendarSession,
    TwseTradingCalendarSnapshot,
    calendar_snapshot_hash,
    read_trading_calendar_snapshot,
)


def _session(day: int) -> TwseTradingCalendarSession:
    return TwseTradingCalendarSession(
        trading_date=date(2024, 1, day),
        source_version="finmind-calendar-v1",
        source_revision_hash=f"{day:064x}",
        source_payload_hash="a" * 64,
        first_observed_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        available_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        available_at_basis="FIRST_OBSERVED_AT_RETRIEVAL",
        calendar_verification_status="UNRESOLVED",
        market_basis="SCHEDULING_HINT",
        usage_scope="CALENDAR_RESEARCH_ONLY",
        system_status="RESEARCH_ONLY",
        reason_codes=("OFFICIAL_SESSION_TIMES_UNAVAILABLE",),
    )


def _snapshot() -> TwseTradingCalendarSnapshot:
    sessions = (_session(2), _session(3))
    return TwseTradingCalendarSnapshot(
        sessions=sessions,
        calendar_snapshot_sha256=calendar_snapshot_hash(sessions),
    )


def test_calendar_file_roundtrips_with_versioned_snapshot_hash(tmp_path: Path) -> None:
    expected = _snapshot()
    path = tmp_path / "calendar.json"
    path.write_text(
        json.dumps(expected.to_dict(), ensure_ascii=False),
        encoding="utf-8",
    )

    observed = read_trading_calendar_snapshot(path)

    assert observed == expected
    assert observed.session_dates == (date(2024, 1, 2), date(2024, 1, 3))


def test_calendar_file_rejects_session_tampering(tmp_path: Path) -> None:
    payload = _snapshot().to_dict()
    sessions = payload["sessions"]
    assert isinstance(sessions, list)
    sessions[0]["trading_date"] = "2024-01-01"
    path = tmp_path / "tampered-calendar.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TradingCalendarSnapshotError) as captured:
        _ = read_trading_calendar_snapshot(path)

    assert captured.value.reason_code == "TRADING_CALENDAR_SNAPSHOT_MISMATCH"
