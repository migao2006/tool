"""Dependency-light calculations for raw TWSE daily price/volume features."""

from __future__ import annotations

from collections.abc import Sequence
from math import isfinite, log, sqrt
from statistics import fmean, median


def _finite(values: Sequence[float], field_name: str) -> tuple[float, ...]:
    normalized = tuple(float(value) for value in values)
    if not normalized or any(not isfinite(value) for value in normalized):
        raise ValueError(f"{field_name} must contain finite values")
    return normalized


def raw_close_return(closes: Sequence[float]) -> float:
    values = _finite(closes, "closes")
    if len(values) < 2 or values[0] <= 0 or values[-1] <= 0:
        raise ValueError("raw close return needs two positive prices")
    return values[-1] / values[0] - 1.0


def overnight_gap(previous_close: float, current_open: float) -> float:
    previous = float(previous_close)
    current = float(current_open)
    if not isfinite(previous) or not isfinite(current) or min(previous, current) <= 0:
        raise ValueError("overnight gap needs positive finite prices")
    return current / previous - 1.0


def intraday_return(current_open: float, current_close: float) -> float:
    opening = float(current_open)
    closing = float(current_close)
    if not isfinite(opening) or not isfinite(closing) or min(opening, closing) <= 0:
        raise ValueError("intraday return needs positive finite prices")
    return closing / opening - 1.0


def normalized_atr_14(
    previous_and_current_closes: Sequence[float],
    trailing_highs: Sequence[float],
    trailing_lows: Sequence[float],
) -> float:
    closes = _finite(previous_and_current_closes, "closes")
    highs = _finite(trailing_highs, "highs")
    lows = _finite(trailing_lows, "lows")
    if len(closes) != 15 or len(highs) != 14 or len(lows) != 14:
        raise ValueError("ATR14 requires 15 closes and 14 high/low observations")
    if min(closes) <= 0 or min(lows) <= 0:
        raise ValueError("ATR14 prices must be positive")
    true_ranges: list[float] = []
    for index, (high, low) in enumerate(zip(highs, lows, strict=True)):
        if high < low:
            raise ValueError("ATR14 high cannot be below low")
        previous_close = closes[index]
        true_ranges.append(
            max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        )
    return fmean(true_ranges) / closes[-1]


def raw_log_returns(closes: Sequence[float]) -> tuple[float, ...]:
    prices = _finite(closes, "closes")
    if len(prices) < 2 or min(prices) <= 0:
        raise ValueError("log returns need at least two positive closes")
    return tuple(
        log(current / previous)
        for previous, current in zip(prices[:-1], prices[1:], strict=True)
    )


def realized_volatility_20(closes: Sequence[float]) -> float:
    returns = raw_log_returns(closes)
    if len(returns) != 20:
        raise ValueError("realized volatility requires 20 raw log returns")
    return sqrt(sum(value * value for value in returns))


def downside_volatility_20(closes: Sequence[float]) -> float:
    returns = raw_log_returns(closes)
    if len(returns) != 20:
        raise ValueError("downside volatility requires 20 raw log returns")
    return sqrt(sum(min(value, 0.0) ** 2 for value in returns))


def maximum_drawdown_20(closes: Sequence[float]) -> float:
    prices = _finite(closes, "closes")
    if len(prices) != 20 or min(prices) <= 0:
        raise ValueError("maximum drawdown requires 20 positive raw closes")
    peak = prices[0]
    drawdown = 0.0
    for price in prices:
        peak = max(peak, price)
        drawdown = min(drawdown, price / peak - 1.0)
    return drawdown


def average_trading_value_20(trading_values: Sequence[float]) -> float:
    values = _finite(trading_values, "trading values")
    if len(values) != 20 or min(values) < 0:
        raise ValueError("ADV20 requires 20 non-negative trading values")
    return fmean(values)


def volume_anomaly_20(trading_volumes: Sequence[float]) -> float:
    values = _finite(trading_volumes, "trading volumes")
    if len(values) != 20 or min(values) < 0:
        raise ValueError("volume anomaly requires 20 non-negative volumes")
    baseline = median(values)
    if baseline <= 0:
        raise ValueError("volume anomaly median must be positive")
    return values[-1] / baseline - 1.0


def amihud_illiquidity_20(
    closes: Sequence[float],
    trading_values: Sequence[float],
) -> float:
    prices = _finite(closes, "closes")
    turnovers = _finite(trading_values, "trading values")
    if len(prices) != 21 or len(turnovers) != 20:
        raise ValueError("Amihud20 requires 21 closes and 20 trading values")
    if min(prices) <= 0 or min(turnovers) <= 0:
        raise ValueError("Amihud20 requires positive prices and trading values")
    simple_returns = (
        current / previous - 1.0
        for previous, current in zip(prices[:-1], prices[1:], strict=True)
    )
    return fmean(
        abs(return_value) / turnover
        for return_value, turnover in zip(
            simple_returns,
            turnovers,
            strict=True,
        )
    )


__all__ = [
    "amihud_illiquidity_20",
    "average_trading_value_20",
    "downside_volatility_20",
    "intraday_return",
    "maximum_drawdown_20",
    "normalized_atr_14",
    "overnight_gap",
    "raw_close_return",
    "realized_volatility_20",
    "volume_anomaly_20",
]
