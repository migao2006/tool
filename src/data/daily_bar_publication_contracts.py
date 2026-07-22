"""Pure source contracts for one market-wide current daily-bar publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import isfinite
import re


DAILY_BAR_PUBLICATION_SCHEMA_VERSION = "daily-bar-publication.v1"
DAILY_BAR_PUBLICATION_CONTENT_TYPE = "application/vnd.apache.parquet"

_MARKETS = frozenset({"TWSE", "TPEX"})
_MIN_COMMON_STOCK_ROWS_PER_MARKET = 500
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class DailyBarPublicationSourceRow:
    daily_bar_id: int
    security_id: int
    symbol: str
    market: str
    trade_date: date
    open_price: float | None
    high_price: float | None
    low_price: float | None
    close_price: float | None
    trading_volume: float | None
    trading_value: float | None
    trade_count: int | None
    source_id: int
    source_version: str
    available_at: datetime

    def __post_init__(self) -> None:
        if (
            self.daily_bar_id <= 0
            or self.security_id <= 0
            or self.market not in _MARKETS
            or not self.symbol.strip()
            or not self.source_version.strip()
            or self.source_id <= 0
        ):
            raise ValueError("daily-bar publication source row is invalid")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("daily-bar publication available_at must be timezone-aware")
        for value in (
            self.open_price,
            self.high_price,
            self.low_price,
            self.close_price,
            self.trading_volume,
            self.trading_value,
        ):
            if value is not None and not isfinite(value):
                raise ValueError("daily-bar publication numeric value is not finite")

    def canonical_mapping(self) -> dict[str, object]:
        return {
            "daily_bar_id": self.daily_bar_id,
            "security_id": self.security_id,
            "symbol": self.symbol,
            "market": self.market,
            "asset_type": "COMMON_STOCK",
            "trade_date": self.trade_date.isoformat(),
            "open_price": self.open_price,
            "high_price": self.high_price,
            "low_price": self.low_price,
            "close_price": self.close_price,
            "trading_volume": self.trading_volume,
            "trading_value": self.trading_value,
            "trade_count": self.trade_count,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "available_at": self.available_at.astimezone(timezone.utc).isoformat(),
        }

    def parquet_mapping(self) -> dict[str, object]:
        value = self.canonical_mapping()
        value["trade_date"] = self.trade_date
        value["available_at"] = self.available_at.astimezone(timezone.utc)
        return value


@dataclass(frozen=True)
class DailyBarPublicationSourceSnapshot:
    market: str
    trading_date: date
    rows: tuple[DailyBarPublicationSourceRow, ...]
    source_id: int
    source_url: str
    source_versions: tuple[str, ...]
    first_observed_at: datetime
    normalized_content_sha256: str

    def __post_init__(self) -> None:
        if self.market not in _MARKETS or not self.source_url.startswith("https://"):
            raise ValueError("daily-bar publication snapshot scope is invalid")
        if len(self.rows) < _MIN_COMMON_STOCK_ROWS_PER_MARKET:
            raise ValueError("daily-bar publication snapshot coverage is too low")
        if any(
            row.market != self.market
            or row.trade_date != self.trading_date
            or row.source_id != self.source_id
            for row in self.rows
        ):
            raise ValueError("daily-bar publication snapshot contains mixed scope")
        if len({row.security_id for row in self.rows}) != len(self.rows):
            raise ValueError("daily-bar publication snapshot contains duplicate securities")
        if self.first_observed_at.tzinfo is None:
            raise ValueError("daily-bar publication first_observed_at is timezone-naive")
        if _SHA256.fullmatch(self.normalized_content_sha256) is None:
            raise ValueError("daily-bar publication content hash is invalid")


__all__ = [
    "DAILY_BAR_PUBLICATION_CONTENT_TYPE",
    "DAILY_BAR_PUBLICATION_SCHEMA_VERSION",
    "DailyBarPublicationSourceRow",
    "DailyBarPublicationSourceSnapshot",
]
