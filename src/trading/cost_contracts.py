"""Configuration and result types for transaction-cost estimation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from typing import Any, Mapping


ZERO = Decimal("0")
ONE = Decimal("1")


def decimal_value(value: Decimal | int | float | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def taiwan_tick_size(price: Decimal | int | float | str) -> Decimal:
    """Return the common-stock price increment for a positive TWD price."""

    price_value = decimal_value(price)
    if price_value <= ZERO:
        raise ValueError("price must be positive")
    if price_value < Decimal("10"):
        return Decimal("0.01")
    if price_value < Decimal("50"):
        return Decimal("0.05")
    if price_value < Decimal("100"):
        return Decimal("0.1")
    if price_value < Decimal("500"):
        return Decimal("0.5")
    if price_value < Decimal("1000"):
        return Decimal("1")
    return Decimal("5")


@dataclass(frozen=True)
class TransactionCostConfig:
    asset_type: str = "COMMON_STOCK"
    commission_rate: Decimal = Decimal("0.001425")
    commission_discount: Decimal = Decimal("1")
    minimum_fee: Decimal = Decimal("20")
    sell_tax_rate: Decimal = Decimal("0.003")
    estimated_order_notional_ntd: Decimal = Decimal("100000")
    spread_model: str = "TICK_ADV_PROXY"
    slippage_scenario: str = "BASE"
    market_impact_parameter: Decimal = Decimal("0.001")
    max_adv_participation: Decimal = Decimal("0.01")
    version: str = "tw-stock-cost-v1"

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any] | object) -> "TransactionCostConfig":
        """Build from the typed TOML cost section without coupling to its module."""

        names = (
            "asset_type",
            "commission_rate",
            "commission_discount",
            "minimum_fee",
            "sell_tax_rate",
            "estimated_order_notional_ntd",
            "spread_model",
            "slippage_scenario",
            "market_impact_parameter",
            "max_adv_participation",
        )
        getter = settings.get if isinstance(settings, Mapping) else lambda name: getattr(settings, name)
        values = {name: getter(name) for name in names}
        values["version"] = (
            settings.get("profile_version", settings.get("version", "tw-stock-cost-v1"))
            if isinstance(settings, Mapping)
            else getattr(
                settings,
                "profile_version",
                getattr(settings, "version", "tw-stock-cost-v1"),
            )
        )
        return cls(**values)

    def __post_init__(self) -> None:
        decimal_fields = (
            "commission_rate",
            "commission_discount",
            "minimum_fee",
            "sell_tax_rate",
            "estimated_order_notional_ntd",
            "market_impact_parameter",
            "max_adv_participation",
        )
        for field_name in decimal_fields:
            object.__setattr__(self, field_name, decimal_value(getattr(self, field_name)))
        spread_aliases = {
            "TICK_ADV_PROXY": "TICK_ADV_PROXY",
            "TICK_LIQUIDITY_ADV20_V1": "TICK_ADV_PROXY",
        }
        normalized_spread = spread_aliases.get(self.spread_model.upper())
        if normalized_spread is None:
            raise ValueError(f"unsupported spread model: {self.spread_model}")
        object.__setattr__(self, "spread_model", normalized_spread)
        object.__setattr__(self, "slippage_scenario", self.slippage_scenario.upper())
        if self.asset_type != "COMMON_STOCK":
            raise ValueError("the MVP cost contract only supports COMMON_STOCK")
        if self.commission_rate < ZERO or self.sell_tax_rate < ZERO:
            raise ValueError("fee and tax rates cannot be negative")
        if not ZERO < self.commission_discount <= ONE:
            raise ValueError("commission_discount must be in (0, 1]")
        if self.minimum_fee < ZERO or self.estimated_order_notional_ntd <= ZERO:
            raise ValueError("minimum_fee must be non-negative and notional positive")
        if self.market_impact_parameter < ZERO:
            raise ValueError("market_impact_parameter cannot be negative")
        if not ZERO < self.max_adv_participation <= ONE:
            raise ValueError("max_adv_participation must be in (0, 1]")


@dataclass(frozen=True)
class CostBreakdown:
    buy_notional: Decimal
    sell_notional: Decimal
    buy_commission: Decimal
    sell_commission: Decimal
    sell_tax: Decimal
    spread_and_slippage: Decimal
    market_impact: Decimal

    @property
    def total_cost_ntd(self) -> Decimal:
        return (
            self.buy_commission
            + self.sell_commission
            + self.sell_tax
            + self.spread_and_slippage
            + self.market_impact
        )

    @property
    def round_trip_cost_rate(self) -> Decimal:
        if self.buy_notional <= ZERO:
            raise ValueError("buy_notional must be positive")
        return self.total_cost_ntd / self.buy_notional


@dataclass(frozen=True)
class CostProfileEstimate:
    name: str
    multiplier: Decimal
    total_cost_ntd: Decimal
    round_trip_cost_rate: Decimal
    cost_profile_version: str


@dataclass(frozen=True)
class TransactionCostEstimate:
    horizon: int
    breakdown: CostBreakdown
    profiles: Mapping[str, CostProfileEstimate]
    capacity_pass: bool
    adv_participation: Decimal | None
    reason_codes: tuple[str, ...]
    cost_profile_version: str

    def profile(self, name: str = "base_cost") -> CostProfileEstimate:
        try:
            return self.profiles[name.lower()]
        except KeyError as exc:
            raise KeyError(f"unknown cost profile: {name}") from exc


def round_currency(value: Decimal) -> Decimal:
    """Round a monetary estimate upward to the nearest dollar for audit display."""

    return value.quantize(Decimal("1"), rounding=ROUND_CEILING)
