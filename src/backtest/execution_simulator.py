"""Conservative unadjusted-price execution with T+2 cash settlement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Callable, Mapping, Sequence


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class MarketBar:
    """Unadjusted executable prices and point-in-time trading state."""

    trading_date: date
    symbol: str
    open_price: float | None
    close_price: float | None
    volume_shares: float
    suspended: bool = False
    stopped: bool = False
    opening_trade_observed: bool = True
    limit_locked: bool = False
    counterparty_volume_shares: float | None = None
    disposition: bool = False
    periodic_auction: bool = False
    opening_executable_volume_shares: float | None = None
    closing_executable_volume_shares: float | None = None

    def __post_init__(self) -> None:
        volume_fields = (
            self.volume_shares,
            self.counterparty_volume_shares,
            self.opening_executable_volume_shares,
            self.closing_executable_volume_shares,
        )
        if any(value is not None and value < 0 for value in volume_fields):
            raise ValueError("market-bar volumes cannot be negative")


@dataclass(frozen=True)
class Order:
    signal_date: date
    expected_execution_date: date
    symbol: str
    side: OrderSide
    quantity_shares: int

    def __post_init__(self) -> None:
        if self.quantity_shares <= 0:
            raise ValueError("order quantity must be positive")
        if self.expected_execution_date <= self.signal_date:
            raise ValueError("signals cannot execute on the same or an earlier trading date")


@dataclass(frozen=True)
class ExecutionCost:
    commission: float
    tax: float
    slippage: float
    market_impact: float

    @property
    def total(self) -> float:
        return self.commission + self.tax + self.slippage + self.market_impact


@dataclass(frozen=True)
class Fill:
    order: Order
    filled: bool
    price: float | None
    notional: float
    cost: ExecutionCost
    reason_code: str
    settlement_date: date | None = None


CostQuote = Callable[[OrderSide, float, int, MarketBar], ExecutionCost]


@dataclass(frozen=True)
class CompanyAction:
    effective_date: date
    symbol: str
    share_factor: float = 1.0
    cash_dividend_per_share: float = 0.0

    def __post_init__(self) -> None:
        if self.share_factor <= 0 or self.cash_dividend_per_share < 0:
            raise ValueError("company-action factors must be valid")


class CashLedger:
    def __init__(self, initial_cash: float) -> None:
        if initial_cash < 0:
            raise ValueError("initial cash cannot be negative")
        self.settled_cash = float(initial_cash)
        self.unsettled_receivables: list[tuple[date, float]] = []

    def settle_through(self, trading_date: date) -> None:
        remaining: list[tuple[date, float]] = []
        for settlement_date, amount in self.unsettled_receivables:
            if settlement_date <= trading_date:
                self.settled_cash += amount
            else:
                remaining.append((settlement_date, amount))
        self.unsettled_receivables = remaining

    def debit(self, amount: float) -> bool:
        if amount > self.settled_cash:
            return False
        self.settled_cash -= amount
        return True

    def credit_unsettled(self, settlement_date: date, amount: float) -> None:
        self.unsettled_receivables.append((settlement_date, amount))


class ExecutionSimulator:
    """Reject fills when daily data cannot establish reasonable execution."""

    _ZERO_COST = ExecutionCost(0.0, 0.0, 0.0, 0.0)

    def __init__(
        self,
        initial_cash: float,
        trading_dates: Sequence[date],
        maximum_volume_participation: float = 0.01,
    ) -> None:
        if not 0 < maximum_volume_participation <= 1:
            raise ValueError("maximum volume participation must lie in (0, 1]")
        normalized_dates = tuple(trading_dates)
        if len(normalized_dates) < 3:
            raise ValueError("T+2 settlement requires at least three trading dates")
        if normalized_dates != tuple(sorted(set(normalized_dates))):
            raise ValueError("trading dates must be sorted and unique")
        self.cash = CashLedger(initial_cash)
        self.trading_dates = normalized_dates
        self._trading_date_positions = {
            trading_date: position for position, trading_date in enumerate(normalized_dates)
        }
        self.maximum_volume_participation = maximum_volume_participation
        self.positions: dict[str, int] = {}

    @staticmethod
    def _reject(order: Order, reason_code: str) -> Fill:
        return Fill(order, False, None, 0.0, ExecutionSimulator._ZERO_COST, reason_code)

    def _t2_settlement_date(self, trading_date: date) -> date | None:
        position = self._trading_date_positions.get(trading_date)
        if position is None or position + 2 >= len(self.trading_dates):
            return None
        return self.trading_dates[position + 2]

    def execute_at_open(
        self,
        order: Order,
        bar: MarketBar,
        cost_quote: CostQuote,
        settlement_date: date | None = None,
    ) -> Fill:
        if order.side != OrderSide.BUY:
            return self._reject(order, "EXIT_MUST_EXECUTE_AT_CLOSE")
        return self._execute(
            order,
            bar,
            cost_quote,
            bar.open_price,
            bar.opening_executable_volume_shares,
            settlement_date,
        )

    def execute_at_close(
        self,
        order: Order,
        bar: MarketBar,
        cost_quote: CostQuote,
        settlement_date: date | None = None,
    ) -> Fill:
        if order.side != OrderSide.SELL:
            return self._reject(order, "ENTRY_MUST_EXECUTE_AT_OPEN")
        return self._execute(
            order,
            bar,
            cost_quote,
            bar.close_price,
            bar.closing_executable_volume_shares,
            settlement_date,
        )

    def _execute(
        self,
        order: Order,
        bar: MarketBar,
        cost_quote: CostQuote,
        executable_price: float | None,
        executable_volume_shares: float | None,
        settlement_date: date | None,
    ) -> Fill:
        if bar.symbol != order.symbol or bar.trading_date != order.expected_execution_date:
            return self._reject(order, "EXECUTION_BAR_MISMATCH")
        expected_settlement_date = self._t2_settlement_date(bar.trading_date)
        if expected_settlement_date is None:
            return self._reject(order, "T2_SETTLEMENT_DATE_UNAVAILABLE")
        if settlement_date is not None and settlement_date != expected_settlement_date:
            return self._reject(order, "INVALID_T2_SETTLEMENT_DATE")
        self.cash.settle_through(bar.trading_date)
        if bar.suspended or bar.stopped:
            return self._reject(order, "TRADING_SUSPENDED_OR_STOPPED")
        if bar.disposition or bar.periodic_auction:
            return self._reject(order, "RESTRICTED_TRADING_METHOD")
        if order.side == OrderSide.BUY and not bar.opening_trade_observed:
            return self._reject(order, "NO_EXECUTABLE_OPEN")
        if executable_price is None or executable_price <= 0:
            return self._reject(order, "NO_EXECUTABLE_OPEN" if order.side == OrderSide.BUY else "NO_EXECUTABLE_CLOSE")
        if bar.limit_locked and (bar.counterparty_volume_shares is None or bar.counterparty_volume_shares <= 0):
            return self._reject(order, "LIMIT_LOCKED_NO_COUNTERPARTY")
        if bar.limit_locked and order.quantity_shares > float(bar.counterparty_volume_shares):
            return self._reject(order, "LIMIT_LOCKED_INSUFFICIENT_COUNTERPARTY")
        if executable_volume_shares is None:
            return self._reject(order, "EXECUTABLE_VOLUME_MISSING")
        maximum_quantity = executable_volume_shares * self.maximum_volume_participation
        if order.quantity_shares > maximum_quantity:
            return self._reject(order, "VOLUME_CAPACITY_EXCEEDED")
        price = float(executable_price)
        notional = price * order.quantity_shares
        cost = cost_quote(order.side, price, order.quantity_shares, bar)
        if min(cost.commission, cost.tax, cost.slippage, cost.market_impact) < 0:
            raise ValueError("execution costs cannot be negative")
        if order.side == OrderSide.BUY:
            if not self.cash.debit(notional + cost.total):
                return self._reject(order, "INSUFFICIENT_SETTLED_CASH")
            self.positions[order.symbol] = self.positions.get(order.symbol, 0) + order.quantity_shares
            return Fill(
                order,
                True,
                price,
                notional,
                cost,
                "FILLED",
                expected_settlement_date,
            )
        held = self.positions.get(order.symbol, 0)
        if held < order.quantity_shares:
            return self._reject(order, "INSUFFICIENT_POSITION")
        self.positions[order.symbol] = held - order.quantity_shares
        self.cash.credit_unsettled(expected_settlement_date, notional - cost.total)
        return Fill(
            order,
            True,
            price,
            notional,
            cost,
            "FILLED",
            expected_settlement_date,
        )

    def apply_company_action(self, action: CompanyAction) -> None:
        """Apply a point-in-time corporate action to the live unadjusted ledger."""

        held = self.positions.get(action.symbol, 0)
        if held <= 0:
            return
        if action.cash_dividend_per_share:
            self.cash.settled_cash += held * action.cash_dividend_per_share
        adjusted_shares = held * action.share_factor
        if not adjusted_shares.is_integer():
            raise ValueError("fractional corporate-action shares require an explicit cash-in-lieu record")
        self.positions[action.symbol] = int(adjusted_shares)


def fixed_cost_quote(
    commission_rate: float,
    commission_discount: float,
    minimum_fee: float,
    sell_tax_rate: float,
    slippage_rate: float = 0.0,
) -> CostQuote:
    """Small adapter for tests; production should inject transaction_cost.py."""

    def quote(side: OrderSide, price: float, quantity: int, _bar: MarketBar) -> ExecutionCost:
        notional = price * quantity
        commission = max(notional * commission_rate * commission_discount, minimum_fee)
        tax = notional * sell_tax_rate if side == OrderSide.SELL else 0.0
        return ExecutionCost(commission, tax, notional * slippage_rate, 0.0)

    return quote
