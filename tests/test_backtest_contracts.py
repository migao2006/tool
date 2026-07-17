from __future__ import annotations

from datetime import date, timedelta

from src.backtest.execution_simulator import (
    ExecutionSimulator,
    MarketBar,
    Order,
    OrderSide,
    fixed_cost_quote,
)
from src.backtest.walk_forward_backtest import (
    CompletedTrade,
    StaggeredCohortBook,
    cost_sensitivity,
    performance_summary,
)


def test_signal_executes_only_at_next_configured_open() -> None:
    simulator = ExecutionSimulator(initial_cash=1_000_000, maximum_volume_participation=0.01)
    order = Order(date(2026, 1, 1), date(2026, 1, 2), "2330", OrderSide.BUY, 1000)
    wrong_bar = MarketBar(date(2026, 1, 3), "2330", 100.0, 101.0, 1_000_000)
    assert simulator.execute_at_open(order, wrong_bar, fixed_cost_quote(0.001425, 1, 20, 0.003)).filled is False


def test_limit_lock_without_counterparty_is_conservatively_unfilled() -> None:
    simulator = ExecutionSimulator(initial_cash=1_000_000)
    order = Order(date(2026, 1, 1), date(2026, 1, 2), "2330", OrderSide.BUY, 100)
    bar = MarketBar(
        date(2026, 1, 2), "2330", 100.0, 100.0, 1_000_000, limit_locked=True, counterparty_volume_shares=None
    )
    fill = simulator.execute_at_open(order, bar, fixed_cost_quote(0.001425, 1, 20, 0.003))
    assert fill.filled is False
    assert fill.reason_code == "LIMIT_LOCKED_NO_COUNTERPARTY"


def test_t2_sell_proceeds_are_not_immediately_spendable() -> None:
    simulator = ExecutionSimulator(initial_cash=1_000_000)
    quote = fixed_cost_quote(0.001425, 1, 20, 0.003)
    buy = Order(date(2026, 1, 1), date(2026, 1, 2), "2330", OrderSide.BUY, 100)
    bar = MarketBar(date(2026, 1, 2), "2330", 100.0, 100.0, 1_000_000)
    assert simulator.execute_at_open(buy, bar, quote).filled
    cash_before_sale = simulator.cash.settled_cash
    sell = Order(date(2026, 1, 6), date(2026, 1, 7), "2330", OrderSide.SELL, 100)
    sell_bar = MarketBar(date(2026, 1, 7), "2330", 105.0, 105.0, 1_000_000)
    assert simulator.execute_at_close(sell, sell_bar, quote, settlement_date=date(2026, 1, 9)).filled
    assert simulator.cash.settled_cash == cash_before_sale
    simulator.cash.settle_through(date(2026, 1, 9))
    assert simulator.cash.settled_cash > cash_before_sale


def test_staggered_cohort_holds_five_exchange_dates_and_limits_daily_budget() -> None:
    dates = [date(2026, 1, 1) + timedelta(days=index) for index in range(10)]
    book = StaggeredCohortBook(dates, horizon=5)
    assert book.cohort_budget(1_000_000, 0.5) == 100_000
    cohort = book.open(dates[1], 100_000, {"2330": 1.0}, maximum_capital=100_000)
    assert cohort.exit_date == dates[5]
    assert book.due_to_close(dates[5]) == (cohort,)

    import pytest

    with pytest.raises(ValueError, match="daily budget"):
        book.open(dates[2], 100_001, {"2330": 1.0}, maximum_capital=100_000)


def test_cost_stress_changes_backtest_result() -> None:
    trade = CompletedTrade(
        "2330", "LISTED", "SEMICONDUCTOR", "UPTREND", date(2026, 1, 2), date(2026, 1, 8), 100_000, 0.02, 0.005
    )
    results = cost_sensitivity(1_000_000, [trade], multipliers=(1.0, 1.5, 2.0))
    assert results[1.0]["ending_equity"] > results[1.5]["ending_equity"] > results[2.0]["ending_equity"]


def test_annualized_metrics_require_complete_daily_equity_marks() -> None:
    trade = CompletedTrade(
        "2330", "LISTED", "SEMICONDUCTOR", "UPTREND", date(2026, 1, 2), date(2026, 1, 8), 100_000, 0.02, 0.005
    )
    without_marks = performance_summary(1_000_000, [trade])
    assert without_marks["annualized_return"] is None
    assert without_marks["maximum_drawdown"] is None

    daily_marks = [
        (date(2026, 1, 2) + timedelta(days=index), 1_000_000 + index * 100)
        for index in range(5)
    ]
    with_marks = performance_summary(1_000_000, [trade], daily_equity=daily_marks)
    assert with_marks["annualized_return"] is not None
    assert with_marks["maximum_drawdown"] == 0.0
