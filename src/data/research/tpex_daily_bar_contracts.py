"""Immutable contracts for one TPEX daily-bar source revision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from math import isfinite
import re


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class TpexDailyBar:
    daily_bar_id: int
    security_id: int
    trade_date: date
    open_price: float | None
    high_price: float | None
    low_price: float | None
    close_price: float | None
    trading_volume: float | None
    trading_value: float | None
    source_id: int
    source_version: str
    available_at: datetime

    def __post_init__(self) -> None:
        if min(self.daily_bar_id, self.security_id, self.source_id) <= 0:
            raise ValueError("daily-bar identifiers must be positive")
        if not self.source_version.strip():
            raise ValueError("source_version must not be empty")
        object.__setattr__(
            self,
            "available_at",
            _aware(self.available_at, "available_at"),
        )
        prices = tuple(
            value
            for value in (
                self.open_price,
                self.high_price,
                self.low_price,
                self.close_price,
            )
            if value is not None
        )
        if any(not isfinite(value) or value <= 0 for value in prices):
            raise ValueError("daily-bar prices must be finite and positive")
        if (
            self.open_price is not None
            and self.high_price is not None
            and self.low_price is not None
            and self.close_price is not None
            and (
                self.low_price > min(self.open_price, self.close_price)
                or self.high_price < max(self.open_price, self.close_price)
            )
        ):
            raise ValueError("daily-bar OHLC range is invalid")
        for value in (self.trading_volume, self.trading_value):
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError("daily-bar volume and value must be non-negative")

    def hash_values(self) -> dict[str, object]:
        return {
            "available_at": self.available_at.isoformat(),
            "close_price": self.close_price,
            "daily_bar_id": self.daily_bar_id,
            "high_price": self.high_price,
            "low_price": self.low_price,
            "open_price": self.open_price,
            "security_id": self.security_id,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "trade_date": self.trade_date.isoformat(),
            "trading_value": self.trading_value,
            "trading_volume": self.trading_volume,
        }


def daily_bar_revision_hash(
    *,
    as_of_date: date,
    source_id: int,
    source_version: str,
    rows: tuple[TpexDailyBar, ...],
) -> str:
    payload = {
        "as_of_date": as_of_date.isoformat(),
        "market": "TPEX",
        "rows": [row.hash_values() for row in rows],
        "source_id": source_id,
        "source_version": source_version,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class TpexDailyBarRevision:
    as_of_date: date
    source_id: int
    source_version: str
    rows: tuple[TpexDailyBar, ...]
    snapshot_sha256: str

    def __post_init__(self) -> None:
        if self.source_id <= 0 or not self.source_version.strip() or not self.rows:
            raise ValueError("TPEX daily-bar snapshot is incomplete")
        if _SHA256.fullmatch(self.snapshot_sha256) is None:
            raise ValueError("TPEX daily-bar snapshot hash is invalid")
        security_ids = tuple(row.security_id for row in self.rows)
        if tuple(sorted(security_ids)) != security_ids or len(set(security_ids)) != len(
            security_ids
        ):
            raise ValueError("TPEX daily bars must be unique and security-id sorted")
        if any(
            row.trade_date != self.as_of_date
            or row.source_id != self.source_id
            or row.source_version != self.source_version
            for row in self.rows
        ):
            raise ValueError("TPEX daily bars disagree with their source revision")
        expected = daily_bar_revision_hash(
            as_of_date=self.as_of_date,
            source_id=self.source_id,
            source_version=self.source_version,
            rows=self.rows,
        )
        if expected != self.snapshot_sha256:
            raise ValueError("TPEX daily-bar snapshot hash does not match its rows")

    @property
    def by_security_id(self) -> dict[int, TpexDailyBar]:
        return {row.security_id: row for row in self.rows}


def daily_bar_series_hash(
    revisions: tuple[TpexDailyBarRevision, ...],
) -> str:
    encoded = json.dumps(
        [
            {
                "as_of_date": revision.as_of_date.isoformat(),
                "snapshot_sha256": revision.snapshot_sha256,
                "source_id": revision.source_id,
                "source_version": revision.source_version,
            }
            for revision in revisions
        ],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class TpexDailyBarSeriesSnapshot:
    revisions: tuple[TpexDailyBarRevision, ...]
    snapshot_sha256: str

    def __post_init__(self) -> None:
        if not self.revisions:
            raise ValueError("TPEX daily-bar series must contain revisions")
        dates = tuple(revision.as_of_date for revision in self.revisions)
        if tuple(sorted(dates)) != dates or len(set(dates)) != len(dates):
            raise ValueError("TPEX daily-bar revisions must be unique and date sorted")
        source_ids = {revision.source_id for revision in self.revisions}
        if len(source_ids) != 1:
            raise ValueError("TPEX daily-bar revisions must share one source")
        if daily_bar_series_hash(self.revisions) != self.snapshot_sha256:
            raise ValueError("TPEX daily-bar series hash does not match revisions")

    @property
    def as_of_date(self) -> date:
        return self.revisions[-1].as_of_date

    @property
    def row_count(self) -> int:
        return sum(len(revision.rows) for revision in self.revisions)


__all__ = [
    "TpexDailyBar",
    "TpexDailyBarRevision",
    "TpexDailyBarSeriesSnapshot",
    "daily_bar_revision_hash",
    "daily_bar_series_hash",
]
