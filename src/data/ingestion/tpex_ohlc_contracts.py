"""Strict research-only contracts for official TPEx price-index OHLC."""

# pyright: reportUnnecessaryIsInstance=false

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import re


TPEX_OHLC_SCHEMA_VERSION = "tpex_price_index_ohlc.v1"
TPEX_OHLC_SYMBOL = "TPEX_INDEX"
TPEX_OHLC_FIELDS = ("Date", "Open", "High", "Low", "Close", "Change(%)")
TPEX_OHLC_REASON_CODES = (
    "POINT_IN_TIME_UNVERIFIED",
    "AVAILABLE_AT_FIRST_RETRIEVAL_ONLY",
    "HISTORICAL_VINTAGE_UNAVAILABLE",
    "PRICE_INDEX_NOT_TOTAL_RETURN",
    "RAW_LANDING_ONLY",
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class TpexOhlcObservation:
    source_row_index: int
    source_row: tuple[str, str, str, str, str, str]
    landing_key: str
    source_revision_hash: str
    trade_date: date
    open_index: Decimal
    high_index: Decimal
    low_index: Decimal
    close_index: Decimal

    def __post_init__(self) -> None:
        if (
            isinstance(self.source_row_index, bool)
            or not isinstance(self.source_row_index, int)
            or self.source_row_index < 0
        ):
            raise ValueError("source_row_index cannot be negative")
        if (
            not isinstance(self.source_row, tuple)
            or len(self.source_row) != len(TPEX_OHLC_FIELDS)
            or any(not isinstance(value, str) for value in self.source_row)
        ):
            raise ValueError("source_row must match the TPEx OHLC field contract")
        if not _SHA256_PATTERN.fullmatch(
            self.landing_key
        ) or not _SHA256_PATTERN.fullmatch(self.source_revision_hash):
            raise ValueError("TPEx row provenance must use SHA-256 digests")
        if type(self.trade_date) is not date:
            raise ValueError("trade_date must be a date value")
        values = (
            self.open_index,
            self.high_index,
            self.low_index,
            self.close_index,
        )
        if any(
            not isinstance(value, Decimal) or not value.is_finite() or value <= 0
            for value in values
        ):
            raise ValueError("TPEx OHLC values must be finite and positive")
        if self.high_index < max(values):
            raise ValueError("high_index must cover every OHLC value")
        if self.low_index > min(values):
            raise ValueError("low_index must cover every OHLC value")


@dataclass(frozen=True)
class NormalizedTpexOhlcBatch:
    requested_month: date
    response_date: date
    source_version: str
    source_url: str
    source_payload_sha256: str
    retrieved_at: datetime
    available_at: datetime
    rows: tuple[TpexOhlcObservation, ...]
    point_in_time_status: str = "UNVERIFIED"
    usage_scope: str = "RAW_LANDING_ONLY"
    system_status: str = "RESEARCH_ONLY"
    reason_codes: tuple[str, ...] = TPEX_OHLC_REASON_CODES

    def __post_init__(self) -> None:
        if (
            type(self.requested_month) is not date
            or type(self.response_date) is not date
            or self.requested_month.day != 1
            or self.response_date != self.requested_month
        ):
            raise ValueError("TPEx response_date must equal the requested month")
        if not self.source_version or not self.source_url.startswith("https://"):
            raise ValueError("TPEx source provenance is incomplete")
        digest = self.source_payload_sha256.lower()
        if not _SHA256_PATTERN.fullmatch(digest):
            raise ValueError("source_payload_sha256 must be a SHA-256 hex digest")
        timestamps = (self.retrieved_at, self.available_at)
        if any(
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
            for value in timestamps
        ):
            raise ValueError("TPEx timestamps must be timezone-aware")
        if self.available_at != self.retrieved_at:
            raise ValueError("available_at must equal retrieved_at")
        if (
            not isinstance(self.rows, tuple)
            or not self.rows
            or any(not isinstance(row, TpexOhlcObservation) for row in self.rows)
        ):
            raise ValueError("TPEx monthly OHLC batch cannot be empty")
        trade_dates = [row.trade_date for row in self.rows]
        if len(trade_dates) != len(set(trade_dates)):
            raise ValueError("TPEx monthly OHLC batch contains duplicate trade dates")
        if trade_dates != sorted(trade_dates):
            raise ValueError("TPEx monthly OHLC trade dates must be strictly ascending")
        if any(
            (trade_date.year, trade_date.month)
            != (self.requested_month.year, self.requested_month.month)
            for trade_date in trade_dates
        ):
            raise ValueError("TPEx trade date is outside the requested month")
        if (
            self.point_in_time_status != "UNVERIFIED"
            or self.usage_scope != "RAW_LANDING_ONLY"
            or self.system_status != "RESEARCH_ONLY"
            or self.reason_codes != TPEX_OHLC_REASON_CODES
        ):
            raise ValueError("TPEx OHLC data must remain research-only raw landing")
        observed_at = self.retrieved_at.astimezone(timezone.utc)
        object.__setattr__(self, "source_payload_sha256", digest)
        object.__setattr__(self, "retrieved_at", observed_at)
        object.__setattr__(self, "available_at", observed_at)
