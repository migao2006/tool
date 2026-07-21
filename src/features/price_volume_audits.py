"""Window construction and per-value audits for price/volume features."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from math import isfinite

from .price_volume_calculations import (
    amihud_illiquidity_20,
    average_trading_value_20,
    downside_volatility_20,
    intraday_return,
    maximum_drawdown_20,
    normalized_atr_14,
    overnight_gap,
    raw_close_return,
    realized_volatility_20,
    volume_anomaly_20,
)
from .price_volume_contracts import FeatureValueAudit
from .price_volume_input import CanonicalResearchBar, FeatureInputError
from .price_volume_schema import PRICE_VOLUME_FEATURE_NAMES


FeatureCalculator = Callable[[Sequence[CanonicalResearchBar]], float]


def _window(
    *,
    feature_name: str,
    current: CanonicalResearchBar,
    count: int,
    session_positions: Mapping[date, int],
    sessions: Sequence[date],
    bars_by_date: Mapping[date, CanonicalResearchBar],
) -> tuple[tuple[CanonicalResearchBar, ...], tuple[str, ...], date | None]:
    position = session_positions[current.trade_date]
    start_position = position - count + 1
    if start_position < 0:
        return (), (f"INSUFFICIENT_HISTORY:{feature_name}",), None
    expected_dates = tuple(sessions[start_position : position + 1])
    window = tuple(
        bars_by_date[session] for session in expected_dates if session in bars_by_date
    )
    if len(window) != count:
        return window, (f"MISSING_CANONICAL_BAR:{feature_name}",), expected_dates[0]
    return window, (), expected_dates[0]


def _audit_feature(
    *,
    feature_name: str,
    current: CanonicalResearchBar,
    count: int,
    session_positions: Mapping[date, int],
    sessions: Sequence[date],
    bars_by_date: Mapping[date, CanonicalResearchBar],
    calculate: FeatureCalculator,
) -> FeatureValueAudit:
    window, window_reasons, source_start = _window(
        feature_name=feature_name,
        current=current,
        count=count,
        session_positions=session_positions,
        sessions=sessions,
        bars_by_date=bars_by_date,
    )
    reasons = list(window_reasons)
    limitations: list[str] = []
    for bar in window:
        reasons.extend(bar.record_reason_codes)
        limitations.extend(bar.record_research_limitation_reason_codes)
    available_at = max((bar.available_at for bar in window), default=None)
    observed_available_at = max(
        (bar.observed_available_at for bar in window),
        default=None,
    )
    if any(bar.available_at > current.decision_at for bar in window):
        reasons.append("POINT_IN_TIME_VIOLATION")
    value: float | None = None
    if not reasons:
        try:
            value = float(calculate(window))
            if not isfinite(value):
                raise ValueError("feature result is not finite")
        except FeatureInputError as error:
            reasons.append(error.reason_code)
        except (ArithmeticError, ValueError):
            reasons.append(f"FEATURE_CALCULATION_INVALID:{feature_name}")
    return FeatureValueAudit(
        feature_name=feature_name,
        value=value,
        availability_mode=current.availability_mode,
        available_at=available_at,
        observed_available_at=observed_available_at,
        source_start_date=source_start,
        source_end_date=current.trade_date,
        source_row_count=len(window),
        source_available_at_bases=tuple(
            dict.fromkeys(bar.available_at_basis or "UNSPECIFIED" for bar in window)
        ),
        reason_codes=tuple(dict.fromkeys(reasons)),
        research_limitation_reason_codes=tuple(dict.fromkeys(limitations)),
    )


def build_feature_audits(
    *,
    current: CanonicalResearchBar,
    session_positions: Mapping[date, int],
    sessions: Sequence[date],
    bars_by_date: Mapping[date, CanonicalResearchBar],
) -> dict[str, FeatureValueAudit]:
    audits: dict[str, FeatureValueAudit] = {}

    def add(name: str, count: int, calculate: FeatureCalculator) -> None:
        audits[name] = _audit_feature(
            feature_name=name,
            current=current,
            count=count,
            session_positions=session_positions,
            sessions=sessions,
            bars_by_date=bars_by_date,
            calculate=calculate,
        )

    for lag in (1, 2, 3, 5, 10, 20, 60):
        add(
            f"raw_close_return_{lag}d",
            lag + 1,
            lambda window: raw_close_return(
                (window[0].value("close_price"), window[-1].value("close_price"))
            ),
        )
    add(
        "overnight_gap_1d",
        2,
        lambda window: overnight_gap(
            window[0].value("close_price"),
            window[1].value("open_price"),
        ),
    )
    add(
        "intraday_return_1d",
        1,
        lambda window: intraday_return(
            window[0].value("open_price"),
            window[0].value("close_price"),
        ),
    )
    add(
        "atr_14",
        15,
        lambda window: normalized_atr_14(
            tuple(bar.value("close_price") for bar in window),
            tuple(bar.value("high_price") for bar in window[1:]),
            tuple(bar.value("low_price") for bar in window[1:]),
        ),
    )
    for name, calculator in (
        ("realized_volatility_20", realized_volatility_20),
        ("downside_volatility_20", downside_volatility_20),
    ):
        add(
            name,
            21,
            lambda window, calculate=calculator: calculate(
                tuple(bar.value("close_price") for bar in window)
            ),
        )
    add(
        "maximum_drawdown_20",
        20,
        lambda window: maximum_drawdown_20(
            tuple(bar.value("close_price") for bar in window)
        ),
    )
    for name in ("adv20_ntd", "turnover_ntd_mean_20"):
        add(
            name,
            20,
            lambda window: average_trading_value_20(
                tuple(bar.value("trading_value") for bar in window)
            ),
        )
    add(
        "volume_anomaly_20",
        20,
        lambda window: volume_anomaly_20(
            tuple(bar.value("trading_volume") for bar in window)
        ),
    )
    add(
        "amihud_illiquidity_20",
        21,
        lambda window: amihud_illiquidity_20(
            tuple(bar.value("close_price") for bar in window),
            tuple(bar.value("trading_value") for bar in window[1:]),
        ),
    )
    if tuple(audits) != PRICE_VOLUME_FEATURE_NAMES:
        raise AssertionError("feature builder order drifted from the frozen schema")
    return audits


__all__ = ["build_feature_audits"]
