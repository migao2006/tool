"""Versioned, file-backed TWSE trading-calendar snapshot contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import cast


TRADING_CALENDAR_SNAPSHOT_VERSION = "twse-trading-calendar-snapshot.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class TradingCalendarSnapshotError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.reason_code: str = "TRADING_CALENDAR_SNAPSHOT_MISMATCH"


def _text(row: Mapping[str, object], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        raise TradingCalendarSnapshotError(
            "Trading-calendar snapshot contains incomplete provenance"
        )
    return value.strip()


def _date(row: Mapping[str, object], name: str) -> date:
    value = row.get(name)
    try:
        return value if type(value) is date else date.fromisoformat(str(value))
    except ValueError as error:
        raise TradingCalendarSnapshotError(
            "Trading-calendar snapshot contains an invalid date"
        ) from error


def _timestamp(row: Mapping[str, object], name: str) -> datetime:
    value = row.get(name)
    try:
        parsed = (
            value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        )
    except ValueError as error:
        raise TradingCalendarSnapshotError(
            "Trading-calendar snapshot contains an invalid timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TradingCalendarSnapshotError(
            "Trading-calendar timestamps must be timezone-aware"
        )
    return parsed.astimezone(timezone.utc)


def _reason_codes(row: Mapping[str, object]) -> tuple[str, ...]:
    value = row.get("reason_codes")
    if not isinstance(value, (list, tuple)):
        raise TradingCalendarSnapshotError(
            "Trading-calendar reason codes must be an array"
        )
    values = cast(Sequence[object], value)
    if any(not isinstance(item, str) or not item for item in values):
        raise TradingCalendarSnapshotError(
            "Trading-calendar reason codes contain an invalid value"
        )
    return tuple(cast(str, item) for item in values)


@dataclass(frozen=True)
class TwseTradingCalendarSession:
    trading_date: date
    source_version: str
    source_revision_hash: str
    source_payload_hash: str
    first_observed_at: datetime
    available_at: datetime
    available_at_basis: str
    calendar_verification_status: str
    market_basis: str
    usage_scope: str
    system_status: str
    reason_codes: tuple[str, ...]
    market: str = "TWSE"
    is_trading_day: bool = True

    def __post_init__(self) -> None:
        if self.market != "TWSE" or not self.is_trading_day:
            raise ValueError("calendar snapshot accepts TWSE trading sessions only")
        if (
            _SHA256.fullmatch(self.source_revision_hash) is None
            or _SHA256.fullmatch(self.source_payload_hash) is None
        ):
            raise ValueError("calendar session contains an invalid source digest")
        for value in (self.first_observed_at, self.available_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("calendar session timestamps must be timezone-aware")
        if self.available_at_basis not in {
            "OFFICIAL_PUBLICATION_AT",
            "VERSIONED_SNAPSHOT",
            "FIRST_OBSERVED_AT_RETRIEVAL",
        }:
            raise ValueError("calendar available_at basis is invalid")
        if self.available_at_basis == "OFFICIAL_PUBLICATION_AT":
            if self.available_at > self.first_observed_at:
                raise ValueError("official calendar publication cannot follow retrieval")
        elif self.available_at != self.first_observed_at:
            raise ValueError("snapshot calendar availability must equal first observation")
        if self.calendar_verification_status not in {
            "VERIFIED",
            "UNRESOLVED",
            "CONFLICT",
        }:
            raise ValueError("calendar verification status is invalid")
        if self.market_basis not in {"SOURCE_ASSERTED", "SCHEDULING_HINT"}:
            raise ValueError("calendar market basis is invalid")
        formally_verified = (
            self.calendar_verification_status == "VERIFIED"
            and self.market_basis == "SOURCE_ASSERTED"
            and self.available_at_basis
            in {"OFFICIAL_PUBLICATION_AT", "VERSIONED_SNAPSHOT"}
            and self.usage_scope == "POINT_IN_TIME_CALENDAR"
            and self.system_status == "PASS"
            and not self.reason_codes
        )
        research_only = (
            self.calendar_verification_status in {"UNRESOLVED", "CONFLICT"}
            and self.usage_scope == "CALENDAR_RESEARCH_ONLY"
            and self.system_status == "RESEARCH_ONLY"
            and bool(self.reason_codes)
        )
        if not (formally_verified or research_only):
            raise ValueError("calendar session status contract is inconsistent")
        if not all(
            value.strip()
            for value in (
                self.source_version,
                self.usage_scope,
            )
        ):
            raise ValueError("calendar session provenance is incomplete")

    @classmethod
    def from_mapping(
        cls,
        row: Mapping[str, object],
    ) -> "TwseTradingCalendarSession":
        try:
            return cls(
                market=_text(row, "market").upper(),
                trading_date=_date(row, "trading_date"),
                is_trading_day=row.get("is_trading_day") is True,
                source_version=_text(row, "source_version"),
                source_revision_hash=_text(row, "source_revision_hash").lower(),
                source_payload_hash=_text(row, "source_payload_hash").lower(),
                first_observed_at=_timestamp(row, "first_observed_at"),
                available_at=_timestamp(row, "available_at"),
                available_at_basis=_text(row, "available_at_basis"),
                calendar_verification_status=_text(
                    row, "calendar_verification_status"
                ),
                market_basis=_text(row, "market_basis"),
                usage_scope=_text(row, "usage_scope"),
                system_status=_text(row, "system_status"),
                reason_codes=_reason_codes(row),
            )
        except ValueError as error:
            raise TradingCalendarSnapshotError(
                "Trading-calendar session violates the versioned contract"
            ) from error


def calendar_snapshot_hash(
    sessions: Sequence[TwseTradingCalendarSession],
) -> str:
    payload = {
        "market": "TWSE",
        "schema_version": TRADING_CALENDAR_SNAPSHOT_VERSION,
        "sessions": [
            {
                **asdict(session),
                "trading_date": session.trading_date.isoformat(),
                "first_observed_at": session.first_observed_at.isoformat(),
                "available_at": session.available_at.isoformat(),
                "reason_codes": list(session.reason_codes),
            }
            for session in sessions
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class TwseTradingCalendarSnapshot:
    sessions: tuple[TwseTradingCalendarSession, ...]
    calendar_snapshot_sha256: str
    schema_version: str = TRADING_CALENDAR_SNAPSHOT_VERSION
    market: str = "TWSE"

    def __post_init__(self) -> None:
        dates = tuple(session.trading_date for session in self.sessions)
        if (
            not self.sessions
            or dates != tuple(sorted(dates))
            or len(set(dates)) != len(dates)
        ):
            raise ValueError("calendar sessions must be non-empty, ordered, and unique")
        if self.schema_version != TRADING_CALENDAR_SNAPSHOT_VERSION:
            raise ValueError("trading-calendar snapshot version is unsupported")
        if self.market != "TWSE":
            raise ValueError("trading-calendar snapshot market must be TWSE")
        if self.calendar_snapshot_sha256 != calendar_snapshot_hash(self.sessions):
            raise ValueError("trading-calendar snapshot hash is invalid")

    @property
    def session_dates(self) -> tuple[date, ...]:
        return tuple(session.trading_date for session in self.sessions)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "market": self.market,
            "calendar_snapshot_sha256": self.calendar_snapshot_sha256,
            "sessions": [
                {
                    **asdict(session),
                    "trading_date": session.trading_date.isoformat(),
                    "first_observed_at": session.first_observed_at.isoformat(),
                    "available_at": session.available_at.isoformat(),
                    "reason_codes": list(session.reason_codes),
                }
                for session in self.sessions
            ],
        }

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, object],
    ) -> "TwseTradingCalendarSnapshot":
        raw_sessions = cast(object, value.get("sessions"))
        if not isinstance(raw_sessions, list):
            raise TradingCalendarSnapshotError(
                "Trading-calendar snapshot must contain session rows"
            )
        rows = cast(list[object], raw_sessions)
        if not all(isinstance(row, Mapping) for row in rows):
            raise TradingCalendarSnapshotError(
                "Trading-calendar snapshot must contain session rows"
            )
        sessions = tuple(
            TwseTradingCalendarSession.from_mapping(cast(Mapping[str, object], row))
            for row in rows
        )
        try:
            return cls(
                sessions=sessions,
                calendar_snapshot_sha256=_text(
                    value, "calendar_snapshot_sha256"
                ).lower(),
                schema_version=_text(value, "schema_version"),
                market=_text(value, "market").upper(),
            )
        except ValueError as error:
            raise TradingCalendarSnapshotError(
                "Trading-calendar snapshot metadata does not match its sessions"
            ) from error


def read_trading_calendar_snapshot(path: str | Path) -> TwseTradingCalendarSnapshot:
    try:
        payload = cast(
            object,
            json.loads(Path(path).read_text(encoding="utf-8")),
        )
    except (OSError, json.JSONDecodeError) as error:
        raise TradingCalendarSnapshotError(
            "Unable to read the trading-calendar snapshot"
        ) from error
    if not isinstance(payload, Mapping):
        raise TradingCalendarSnapshotError(
            "Trading-calendar snapshot JSON must be an object"
        )
    return TwseTradingCalendarSnapshot.from_mapping(
        cast(Mapping[str, object], payload)
    )


__all__ = [
    "TRADING_CALENDAR_SNAPSHOT_VERSION",
    "TradingCalendarSnapshotError",
    "TwseTradingCalendarSession",
    "TwseTradingCalendarSnapshot",
    "calendar_snapshot_hash",
    "read_trading_calendar_snapshot",
]
