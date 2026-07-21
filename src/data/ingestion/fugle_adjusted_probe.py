"""Bounded, read-only comparison of Fugle raw and adjusted daily candles."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from math import isfinite
from time import sleep
from typing import Protocol, cast, final

from src.data.providers.contracts import ProviderPayload
from src.data.providers.errors import ProviderError
from src.data.providers.validation import require_identifier

from .fugle_adjusted_probe_contracts import (
    FugleAdjustedProbeSummary,
    FugleCandleSeriesProbe,
)


MAX_RANGE_DAYS = 366
Ohlc = tuple[Decimal, Decimal, Decimal, Decimal]


class FugleAdjustedProbeClient(Protocol):
    def historical_candles(
        self,
        symbol: str,
        *,
        start_date: date | str,
        end_date: date | str,
        adjusted: bool = False,
    ) -> ProviderPayload: ...


class FugleAdjustedProbeError(ProviderError):
    """The capability response failed a bounded probe safety check."""


def validate_probe_request(
    *,
    symbol: str,
    start_date: date,
    end_date: date,
    pacing_seconds: float,
) -> str:
    normalized_symbol = require_identifier(symbol, field="symbol")
    if end_date < start_date:
        raise FugleAdjustedProbeError(
            "FUGLE_ADJUSTED_PROBE_DATE_RANGE_INVALID",
            "start_date must not be after end_date",
        )
    if (end_date - start_date).days + 1 > MAX_RANGE_DAYS:
        raise FugleAdjustedProbeError(
            "FUGLE_ADJUSTED_PROBE_DATE_RANGE_LIMIT",
            "Fugle historical candle probe cannot exceed one year",
        )
    if not isfinite(pacing_seconds) or not 0 <= pacing_seconds <= 60:
        raise FugleAdjustedProbeError(
            "FUGLE_ADJUSTED_PROBE_PACING_INVALID",
            "pacing_seconds must be between 0 and 60",
        )
    return normalized_symbol


def _decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise FugleAdjustedProbeError(
            "FUGLE_ADJUSTED_PROBE_ROW_INVALID",
            f"Fugle candle {field} must be numeric",
        )
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise FugleAdjustedProbeError(
            "FUGLE_ADJUSTED_PROBE_ROW_INVALID",
            f"Fugle candle {field} must be numeric",
        ) from error
    if not result.is_finite() or result <= 0:
        raise FugleAdjustedProbeError(
            "FUGLE_ADJUSTED_PROBE_ROW_INVALID",
            f"Fugle candle {field} must be finite and positive",
        )
    return result


def _series(
    payload: ProviderPayload,
    *,
    symbol: str,
    start_date: date,
    end_date: date,
    adjusted: bool,
) -> tuple[dict[date, Ohlc], FugleCandleSeriesProbe]:
    if payload.provider != "FUGLE" or payload.dataset != "historical_candles":
        raise FugleAdjustedProbeError(
            "FUGLE_ADJUSTED_PROBE_PAYLOAD_INVALID",
            "Fugle probe received an unexpected provider or dataset",
        )
    expected_adjusted = str(adjusted).lower()
    if payload.request_metadata.get("adjusted") != expected_adjusted:
        raise FugleAdjustedProbeError(
            "FUGLE_ADJUSTED_PROBE_METADATA_MISMATCH",
            "Fugle response provenance does not match adjusted request",
        )
    raw_payload = cast(object, payload.payload)
    if not isinstance(raw_payload, dict):
        raise FugleAdjustedProbeError(
            "FUGLE_ADJUSTED_PROBE_PAYLOAD_INVALID",
            "Fugle response must be a JSON object",
        )
    body = cast(Mapping[str, object], raw_payload)
    response_symbol = body.get("symbol")
    if response_symbol is not None and response_symbol != symbol:
        raise FugleAdjustedProbeError(
            "FUGLE_ADJUSTED_PROBE_SYMBOL_MISMATCH",
            "Fugle response symbol does not match the request",
        )
    timeframe = body.get("timeframe")
    if timeframe is not None and timeframe != "D":
        raise FugleAdjustedProbeError(
            "FUGLE_ADJUSTED_PROBE_TIMEFRAME_MISMATCH",
            "Fugle response timeframe must be daily",
        )
    raw_rows_value = body.get("data")
    if not isinstance(raw_rows_value, list) or not raw_rows_value:
        raise FugleAdjustedProbeError(
            "FUGLE_ADJUSTED_PROBE_EMPTY",
            "Fugle response must contain at least one candle",
        )
    raw_rows = cast(list[object], raw_rows_value)

    rows: dict[date, Ohlc] = {}
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            raise FugleAdjustedProbeError(
                "FUGLE_ADJUSTED_PROBE_ROW_INVALID",
                "Fugle candle row must be a JSON object",
            )
        row = cast(Mapping[str, object], raw_row)
        raw_date = row.get("date")
        if not isinstance(raw_date, str):
            raise FugleAdjustedProbeError(
                "FUGLE_ADJUSTED_PROBE_ROW_INVALID",
                "Fugle candle date must use YYYY-MM-DD",
            )
        try:
            observed_date = date.fromisoformat(raw_date)
        except ValueError as error:
            raise FugleAdjustedProbeError(
                "FUGLE_ADJUSTED_PROBE_ROW_INVALID",
                "Fugle candle date must use YYYY-MM-DD",
            ) from error
        if not start_date <= observed_date <= end_date:
            raise FugleAdjustedProbeError(
                "FUGLE_ADJUSTED_PROBE_DATE_OUTSIDE_REQUEST",
                "Fugle candle date falls outside the requested range",
            )
        if observed_date in rows:
            raise FugleAdjustedProbeError(
                "FUGLE_ADJUSTED_PROBE_DUPLICATE_DATE",
                "Fugle candle dates must be unique",
            )
        open_price = _decimal(row.get("open"), field="open")
        high_price = _decimal(row.get("high"), field="high")
        low_price = _decimal(row.get("low"), field="low")
        close_price = _decimal(row.get("close"), field="close")
        if low_price > high_price or not (
            low_price <= open_price <= high_price
            and low_price <= close_price <= high_price
        ):
            raise FugleAdjustedProbeError(
                "FUGLE_ADJUSTED_PROBE_OHLC_INVALID",
                "Fugle candle violates OHLC invariants",
            )
        rows[observed_date] = (
            open_price,
            high_price,
            low_price,
            close_price,
        )

    dates = tuple(rows)
    return rows, FugleCandleSeriesProbe(
        adjusted=adjusted,
        row_count=len(rows),
        minimum_date=min(dates).isoformat(),
        maximum_date=max(dates).isoformat(),
        response_sha256=payload.payload_sha256,
        source_version=payload.source_version,
    )


@final
class FugleAdjustedProbe:
    def __init__(
        self,
        *,
        client: FugleAdjustedProbeClient,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        self._client = client
        self._sleep = sleep_fn

    def run(
        self,
        *,
        symbol: str,
        start_date: date,
        end_date: date,
        pacing_seconds: float = 1.0,
    ) -> FugleAdjustedProbeSummary:
        normalized_symbol = validate_probe_request(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            pacing_seconds=pacing_seconds,
        )
        raw_payload = self._client.historical_candles(
            normalized_symbol,
            start_date=start_date,
            end_date=end_date,
            adjusted=False,
        )
        if pacing_seconds:
            self._sleep(pacing_seconds)
        adjusted_payload = self._client.historical_candles(
            normalized_symbol,
            start_date=start_date,
            end_date=end_date,
            adjusted=True,
        )
        raw_rows, raw_summary = _series(
            raw_payload,
            symbol=normalized_symbol,
            start_date=start_date,
            end_date=end_date,
            adjusted=False,
        )
        adjusted_rows, adjusted_summary = _series(
            adjusted_payload,
            symbol=normalized_symbol,
            start_date=start_date,
            end_date=end_date,
            adjusted=True,
        )
        comparable_dates = raw_rows.keys() & adjusted_rows.keys()
        if not comparable_dates:
            raise FugleAdjustedProbeError(
                "FUGLE_ADJUSTED_PROBE_NO_OVERLAP",
                "raw and adjusted candles have no comparable dates",
            )
        differing = sum(
            raw_rows[value] != adjusted_rows[value] for value in comparable_dates
        )
        return FugleAdjustedProbeSummary(
            symbol=normalized_symbol,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            raw=raw_summary,
            adjusted=adjusted_summary,
            comparable_date_count=len(comparable_dates),
            differing_date_count=differing,
            raw_only_date_count=len(raw_rows.keys() - adjusted_rows.keys()),
            adjusted_only_date_count=len(adjusted_rows.keys() - raw_rows.keys()),
            interpretation=(
                "ADJUSTED_SERIES_DIFFERS"
                if differing
                else "ACCESS_CONFIRMED_NO_DIFFERENCE_IN_WINDOW"
            ),
        )
