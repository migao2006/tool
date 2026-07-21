"""Transparent Taiwan equity round-trip transaction-cost estimation.

The estimator keeps statutory fees separate from uncertain spread, slippage and
market-impact estimates. Sensitivity profiles scale the complete estimated cost and
are tagged so training, inference and backtests can persist the exact profile used.
"""

from __future__ import annotations

from decimal import Decimal
from math import sqrt
from typing import Mapping

from src.core.horizon import PRODUCTION_HORIZON, require_production_horizon
from src.trading.cost_contracts import (
    CostBreakdown,
    CostProfileEstimate,
    TransactionCostConfig,
    TransactionCostEstimate,
    ZERO,
    decimal_value,
    round_currency,
    taiwan_tick_size,
)


ONE = Decimal("1")


class TransactionCostModel:
    """Estimate complete round-trip costs without embedding settings in a model."""

    PROFILE_MULTIPLIERS = {
        "low_cost": Decimal("0.75"),
        "base_cost": Decimal("1"),
        "stressed_cost": Decimal("1.5"),
        "extreme_cost": Decimal("2"),
    }

    def __init__(self, config: TransactionCostConfig | None = None) -> None:
        self.config = config or TransactionCostConfig()

    def commission(self, transaction_value: Decimal | int | float | str) -> Decimal:
        value = decimal_value(transaction_value)
        if value <= ZERO:
            raise ValueError("transaction value must be positive")
        calculated = value * self.config.commission_rate * self.config.commission_discount
        return max(calculated, self.config.minimum_fee)

    def estimate_for_decision(
        self,
        *,
        current_price: Decimal | int | float | str,
        adv20_ntd: Decimal | int | float | str | None,
        bid: Decimal | int | float | str | None = None,
        ask: Decimal | int | float | str | None = None,
        horizon: int = PRODUCTION_HORIZON,
    ) -> TransactionCostEstimate:
        """Estimate a round trip using only information available at decision time.

        The current notional is held constant for fee estimation; this method
        never reads the future t+1 entry or fifth-session exit price.
        """

        if (bid is None) != (ask is None):
            raise ValueError("provide both bid and ask or neither")
        return self.estimate(
            buy_price=current_price,
            sell_price=current_price,
            adv20_ntd=adv20_ntd,
            buy_bid=bid,
            buy_ask=ask,
            sell_bid=bid,
            sell_ask=ask,
            horizon=horizon,
        )

    def estimate(
        self,
        *,
        buy_price: Decimal | int | float | str,
        sell_price: Decimal | int | float | str,
        quantity: Decimal | int | float | str | None = None,
        adv20_ntd: Decimal | int | float | str | None = None,
        buy_bid: Decimal | int | float | str | None = None,
        buy_ask: Decimal | int | float | str | None = None,
        sell_bid: Decimal | int | float | str | None = None,
        sell_ask: Decimal | int | float | str | None = None,
        horizon: int = PRODUCTION_HORIZON,
    ) -> TransactionCostEstimate:
        require_production_horizon(horizon)
        buy = decimal_value(buy_price)
        sell = decimal_value(sell_price)
        if buy <= ZERO or sell <= ZERO:
            raise ValueError("buy and sell prices must be positive")
        units = (
            decimal_value(quantity)
            if quantity is not None
            else self.config.estimated_order_notional_ntd / buy
        )
        if units <= ZERO:
            raise ValueError("quantity must be positive")

        buy_notional = buy * units
        sell_notional = sell * units
        adv = decimal_value(adv20_ntd) if adv20_ntd is not None else None
        participation = buy_notional / adv if adv is not None and adv > ZERO else None
        capacity_pass = participation is not None and participation <= self.config.max_adv_participation
        reasons: list[str] = []
        if adv is None or adv <= ZERO:
            reasons.append("ADV20_MISSING")
        elif not capacity_pass:
            reasons.append("ADV_PARTICIPATION_EXCEEDED")

        spread_cost = self._spread_cost(
            buy=buy,
            sell=sell,
            units=units,
            participation=participation,
            buy_bid=buy_bid,
            buy_ask=buy_ask,
            sell_bid=sell_bid,
            sell_ask=sell_ask,
        )
        impact_rate = ZERO
        if participation is not None and participation > ZERO:
            impact_rate = self.config.market_impact_parameter * decimal_value(sqrt(float(participation)))
        impact_cost = (buy_notional + sell_notional) * impact_rate

        breakdown = CostBreakdown(
            buy_notional=buy_notional,
            sell_notional=sell_notional,
            buy_commission=self.commission(buy_notional),
            sell_commission=self.commission(sell_notional),
            sell_tax=sell_notional * self.config.sell_tax_rate,
            spread_and_slippage=spread_cost,
            market_impact=impact_cost,
        )
        profiles = self._profiles(breakdown)
        return TransactionCostEstimate(
            horizon=horizon,
            breakdown=breakdown,
            profiles=profiles,
            capacity_pass=capacity_pass,
            adv_participation=participation,
            reason_codes=tuple(reasons),
            cost_profile_version=self.config.version,
        )

    def _spread_cost(
        self,
        *,
        buy: Decimal,
        sell: Decimal,
        units: Decimal,
        participation: Decimal | None,
        buy_bid: Decimal | int | float | str | None,
        buy_ask: Decimal | int | float | str | None,
        sell_bid: Decimal | int | float | str | None,
        sell_ask: Decimal | int | float | str | None,
    ) -> Decimal:
        quoted = (buy_bid, buy_ask, sell_bid, sell_ask)
        if all(value is not None for value in quoted):
            entry_spread = decimal_value(buy_ask) - decimal_value(buy_bid)
            exit_spread = decimal_value(sell_ask) - decimal_value(sell_bid)
            if entry_spread < ZERO or exit_spread < ZERO:
                raise ValueError("ask price cannot be below bid price")
            return ((entry_spread + exit_spread) / Decimal("2")) * units

        if any(value is not None for value in quoted):
            raise ValueError("provide all four bid/ask values or none")
        if self.config.spread_model != "TICK_ADV_PROXY":
            raise ValueError(f"unsupported spread model: {self.config.spread_model}")

        liquidity_multiplier = ONE
        if participation is None:
            liquidity_multiplier = Decimal("2")
        elif participation > self.config.max_adv_participation:
            liquidity_multiplier = Decimal("2")
        elif participation > self.config.max_adv_participation / Decimal("2"):
            liquidity_multiplier = Decimal("1.5")
        scenario_multiplier = {
            "LOW": Decimal("0.75"),
            "BASE": ONE,
            "STRESSED": Decimal("1.5"),
            "EXTREME": Decimal("2"),
        }.get(self.config.slippage_scenario.upper())
        if scenario_multiplier is None:
            raise ValueError(f"unsupported slippage scenario: {self.config.slippage_scenario}")
        round_trip_ticks = (taiwan_tick_size(buy) + taiwan_tick_size(sell)) / Decimal("2")
        return round_trip_ticks * units * liquidity_multiplier * scenario_multiplier

    def _profiles(self, breakdown: CostBreakdown) -> Mapping[str, CostProfileEstimate]:
        result: dict[str, CostProfileEstimate] = {}
        for name, multiplier in self.PROFILE_MULTIPLIERS.items():
            total = breakdown.total_cost_ntd * multiplier
            result[name] = CostProfileEstimate(
                name=name,
                multiplier=multiplier,
                total_cost_ntd=total,
                round_trip_cost_rate=total / breakdown.buy_notional,
                cost_profile_version=f"{self.config.version}:{name}",
            )
        return result
