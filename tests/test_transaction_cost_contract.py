from decimal import Decimal

import pytest

from src.trading.transaction_cost import (
    TransactionCostConfig,
    TransactionCostModel,
    taiwan_tick_size,
)


def test_commission_discount_minimum_fee_and_sell_tax_are_applied() -> None:
    model = TransactionCostModel(
        TransactionCostConfig(
            commission_discount=Decimal("0.6"),
            minimum_fee=Decimal("20"),
            market_impact_parameter=Decimal("0"),
        )
    )
    estimate = model.estimate(
        buy_price=Decimal("50"),
        sell_price=Decimal("55"),
        quantity=Decimal("1000"),
        adv20_ntd=Decimal("100000000"),
        buy_bid=Decimal("50"),
        buy_ask=Decimal("50"),
        sell_bid=Decimal("55"),
        sell_ask=Decimal("55"),
    )

    assert estimate.breakdown.buy_commission == Decimal("42.7500000")
    assert estimate.breakdown.sell_commission == Decimal("47.0250000")
    assert estimate.breakdown.sell_tax == Decimal("165.000")
    assert estimate.breakdown.total_cost_ntd == Decimal("254.7750000")
    assert estimate.capacity_pass is True


def test_typed_config_can_initialize_cost_contract_without_hardcoded_translation() -> None:
    config = TransactionCostConfig.from_settings(
        {
            "asset_type": "COMMON_STOCK",
            "commission_rate": 0.001425,
            "commission_discount": 0.6,
            "minimum_fee": 20,
            "sell_tax_rate": 0.003,
            "estimated_order_notional_ntd": 100000,
            "spread_model": "tick_liquidity_adv20_v1",
            "slippage_scenario": "base",
            "market_impact_parameter": 0.1,
            "max_adv_participation": 0.01,
            "profile_version": "test-v1",
        }
    )

    assert config.spread_model == "TICK_ADV_PROXY"
    assert config.slippage_scenario == "BASE"
    assert config.version == "test-v1"


def test_minimum_commission_is_charged_on_both_sides() -> None:
    model = TransactionCostModel(
        TransactionCostConfig(market_impact_parameter=Decimal("0"))
    )
    estimate = model.estimate(
        buy_price=10,
        sell_price=11,
        quantity=1,
        adv20_ntd=100000,
        buy_bid=10,
        buy_ask=10,
        sell_bid=11,
        sell_ask=11,
    )

    assert estimate.breakdown.buy_commission == Decimal("20")
    assert estimate.breakdown.sell_commission == Decimal("20")
    assert estimate.breakdown.sell_tax == Decimal("0.033")


def test_cost_sensitivity_profiles_are_exact_multiples_of_base() -> None:
    estimate = TransactionCostModel(
        TransactionCostConfig(market_impact_parameter=Decimal("0"))
    ).estimate(
        buy_price=100,
        sell_price=102,
        quantity=1000,
        adv20_ntd=100000000,
        buy_bid=100,
        buy_ask=100,
        sell_bid=102,
        sell_ask=102,
    )
    base = estimate.profile("base_cost")

    assert estimate.profile("stressed_cost").total_cost_ntd == base.total_cost_ntd * Decimal("1.5")
    assert estimate.profile("extreme_cost").total_cost_ntd == base.total_cost_ntd * Decimal("2")
    assert estimate.profile("low_cost").total_cost_ntd == base.total_cost_ntd * Decimal("0.75")


def test_capacity_and_quote_validation_are_conservative() -> None:
    model = TransactionCostModel()
    estimate = model.estimate(buy_price=100, sell_price=100, quantity=1000, adv20_ntd=1000000)

    assert estimate.capacity_pass is False
    assert "ADV_PARTICIPATION_EXCEEDED" in estimate.reason_codes
    with pytest.raises(ValueError, match="all four"):
        model.estimate(buy_price=100, sell_price=100, quantity=1, buy_bid=99)

    with pytest.raises(NotImplementedError):
        model.estimate(buy_price=100, sell_price=100, quantity=1, horizon=3)


def test_decision_time_cost_estimate_does_not_require_future_prices() -> None:
    estimate = TransactionCostModel().estimate_for_decision(
        current_price=100,
        adv20_ntd=100_000_000,
        bid=99.9,
        ask=100.0,
    )
    assert estimate.horizon == 5
    assert estimate.profile("base_cost").round_trip_cost_rate > 0


@pytest.mark.parametrize(
    ("price", "tick"),
    [(9, "0.01"), (10, "0.05"), (50, "0.1"), (100, "0.5"), (500, "1"), (1000, "5")],
)
def test_taiwan_tick_table(price: int, tick: str) -> None:
    assert taiwan_tick_size(price) == Decimal(tick)
