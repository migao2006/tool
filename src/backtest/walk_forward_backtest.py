"""Staggered five-day cohort accounting and actual-input performance output."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import sqrt
from statistics import fmean, pstdev
from typing import Iterable, Mapping, Sequence

from ..core.horizon import require_supported_horizon


@dataclass(frozen=True)
class Cohort:
    entry_date: date
    exit_date: date
    capital: float
    positions: Mapping[str, float]


class StaggeredCohortBook:
    """Allocate at most roughly total exposure / horizon to each daily cohort."""

    def __init__(self, trading_dates: Sequence[date], horizon: int = 5) -> None:
        require_supported_horizon(horizon)
        if len(set(trading_dates)) != len(trading_dates) or list(trading_dates) != sorted(trading_dates):
            raise ValueError("trading_dates must be sorted and unique")
        self.trading_dates = list(trading_dates)
        self.horizon = horizon
        self.cohorts: list[Cohort] = []

    def cohort_budget(self, portfolio_equity: float, market_exposure_cap: float) -> float:
        if portfolio_equity < 0 or not 0 <= market_exposure_cap <= 1:
            raise ValueError("portfolio equity and exposure cap must be valid")
        return portfolio_equity * market_exposure_cap / self.horizon

    def open(
        self,
        entry_date: date,
        capital: float,
        positions: Mapping[str, float],
        *,
        maximum_capital: float,
    ) -> Cohort:
        if entry_date not in self.trading_dates:
            raise ValueError("entry date is not in the exchange trading calendar")
        if capital < 0 or maximum_capital < 0 or any(weight < 0 for weight in positions.values()):
            raise ValueError("cohort capital and weights cannot be negative")
        if capital > maximum_capital + 1e-9:
            raise ValueError("cohort capital exceeds the configured daily budget")
        if sum(positions.values()) > 1 + 1e-9:
            raise ValueError("cohort position weights cannot exceed 100%")
        entry_index = self.trading_dates.index(entry_date)
        exit_index = entry_index + self.horizon - 1
        if exit_index >= len(self.trading_dates):
            raise ValueError("not enough future trading dates to close the cohort")
        cohort = Cohort(entry_date, self.trading_dates[exit_index], capital, dict(positions))
        self.cohorts.append(cohort)
        return cohort

    def due_to_close(self, trading_date: date) -> tuple[Cohort, ...]:
        due = tuple(cohort for cohort in self.cohorts if cohort.exit_date == trading_date)
        self.cohorts = [cohort for cohort in self.cohorts if cohort.exit_date != trading_date]
        return due


@dataclass(frozen=True)
class CompletedTrade:
    symbol: str
    market: str
    industry: str
    market_regime: str
    entry_date: date
    exit_date: date
    allocated_capital: float
    gross_return: float
    round_trip_cost_rate: float

    @property
    def net_return(self) -> float:
        return self.gross_return - self.round_trip_cost_rate

    @property
    def net_pnl(self) -> float:
        return self.allocated_capital * self.net_return


def equity_curve(initial_equity: float, dated_pnl: Mapping[date, float]) -> list[tuple[date, float]]:
    if initial_equity <= 0:
        raise ValueError("initial equity must be positive")
    equity = float(initial_equity)
    output: list[tuple[date, float]] = []
    for trading_date in sorted(dated_pnl):
        equity += float(dated_pnl[trading_date])
        output.append((trading_date, equity))
    return output


def maximum_drawdown(equities: Sequence[float]) -> float:
    if not equities:
        return 0.0
    peak = equities[0]
    drawdown = 0.0
    for equity in equities:
        peak = max(peak, equity)
        if peak > 0:
            drawdown = min(drawdown, equity / peak - 1)
    return drawdown


def _daily_risk_metrics(
    initial_equity: float,
    daily_equity: Sequence[tuple[date, float]],
) -> dict[str, float | None]:
    """Calculate risk metrics only when a complete daily mark-to-market curve exists."""

    if not daily_equity:
        raise ValueError("daily_equity cannot be empty")
    dates = [point[0] for point in daily_equity]
    equities = [float(point[1]) for point in daily_equity]
    if dates != sorted(dates) or len(dates) != len(set(dates)):
        raise ValueError("daily_equity dates must be sorted exchange sessions without duplicates")
    if any(value <= 0 for value in equities):
        raise ValueError("daily equity values must be positive")
    returns: list[float] = []
    previous = float(initial_equity)
    for equity in equities:
        returns.append(equity / previous - 1)
        previous = equity
    session_count = len(returns)
    annualized_return = (equities[-1] / initial_equity) ** (252 / session_count) - 1
    standard_deviation = pstdev(returns) if len(returns) > 1 else 0.0
    downside = [min(0.0, value) for value in returns]
    downside_deviation = sqrt(fmean([value * value for value in downside])) if downside else 0.0
    maximum_dd = maximum_drawdown([initial_equity, *equities])
    return {
        "annualized_return": annualized_return,
        "sharpe": None if standard_deviation == 0 else fmean(returns) / standard_deviation * sqrt(252),
        "sortino": None if downside_deviation == 0 else fmean(returns) / downside_deviation * sqrt(252),
        "maximum_drawdown": maximum_dd,
        "calmar": None if maximum_dd == 0 else annualized_return / abs(maximum_dd),
    }


def performance_summary(
    initial_equity: float,
    trades: Iterable[CompletedTrade],
    *,
    daily_equity: Sequence[tuple[date, float]] | None = None,
) -> dict[str, float | int | None]:
    """Summarize supplied executions without fabricating unavailable daily marks.

    Annualized and path-dependent metrics remain ``None`` unless the caller
    supplies a complete exchange-session mark-to-market equity curve.
    """

    materialized = list(trades)
    dated_pnl: dict[date, float] = {}
    for trade in materialized:
        dated_pnl[trade.exit_date] = dated_pnl.get(trade.exit_date, 0.0) + trade.net_pnl
    curve = equity_curve(initial_equity, dated_pnl)
    if not curve:
        return {
            "trade_count": 0,
            "ending_equity": initial_equity,
            "annualized_return": None,
            "sharpe": None,
            "sortino": None,
            "maximum_drawdown": None,
            "calmar": None,
            "hit_rate": None,
            "turnover": 0.0,
            "cost_to_gross_return": None,
        }
    risk_metrics = (
        _daily_risk_metrics(initial_equity, daily_equity)
        if daily_equity is not None
        else {
            "annualized_return": None,
            "sharpe": None,
            "sortino": None,
            "maximum_drawdown": None,
            "calmar": None,
        }
    )
    gross_profit = sum(trade.allocated_capital * trade.gross_return for trade in materialized)
    costs = sum(trade.allocated_capital * trade.round_trip_cost_rate for trade in materialized)
    return {
        "trade_count": len(materialized),
        "ending_equity": curve[-1][1],
        **risk_metrics,
        "hit_rate": sum(trade.net_return > 0 for trade in materialized) / len(materialized),
        "average_win": fmean([trade.net_return for trade in materialized if trade.net_return > 0])
        if any(trade.net_return > 0 for trade in materialized)
        else None,
        "average_loss": fmean([trade.net_return for trade in materialized if trade.net_return < 0])
        if any(trade.net_return < 0 for trade in materialized)
        else None,
        "turnover": sum(trade.allocated_capital * 2 for trade in materialized) / initial_equity,
        "cost_to_gross_return": None if gross_profit == 0 else costs / abs(gross_profit),
    }


def cost_sensitivity(
    initial_equity: float, trades: Iterable[CompletedTrade], multipliers: Sequence[float] = (0.75, 1.0, 1.5, 2.0)
) -> dict[float, dict[str, float | int | None]]:
    materialized = list(trades)
    output: dict[float, dict[str, float | int | None]] = {}
    for multiplier in multipliers:
        if multiplier < 0:
            raise ValueError("cost multiplier cannot be negative")
        stressed = [
            CompletedTrade(
                trade.symbol,
                trade.market,
                trade.industry,
                trade.market_regime,
                trade.entry_date,
                trade.exit_date,
                trade.allocated_capital,
                trade.gross_return,
                trade.round_trip_cost_rate * multiplier,
            )
            for trade in materialized
        ]
        output[float(multiplier)] = performance_summary(initial_equity, stressed)
    return output
