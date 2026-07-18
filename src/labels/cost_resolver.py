"""Resolve versioned label costs from the shared transaction-cost model."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from .contracts import ExecutablePrice, LabelDataError, ZERO, decimal_label_value

if TYPE_CHECKING:
    from src.trading.transaction_cost import TransactionCostModel


def resolve_label_cost(
    *,
    transaction_cost_model: TransactionCostModel | None,
    entry_open: ExecutablePrice,
    exit_close: ExecutablePrice,
    horizon: int,
    round_trip_cost_rate: Decimal | int | float | str | None,
    cost_profile_version: str | None,
    cost_profile: str,
    quantity: Decimal | int | float | str | None,
    adv20_ntd: Decimal | int | float | str | None,
) -> tuple[Decimal, str, tuple[str, ...]]:
    """Return rate, version and hard capacity reasons without hiding missing data."""

    if transaction_cost_model is None:
        if round_trip_cost_rate is None:
            raise LabelDataError(
                "round_trip_cost_rate or a transaction_cost_model is required"
            )
        if not cost_profile_version:
            raise LabelDataError(
                "cost_profile_version is required for an external cost rate"
            )
        cost_rate = decimal_label_value(
            round_trip_cost_rate,
            name="round_trip_cost_rate",
        )
        if cost_rate < ZERO:
            raise ValueError("round-trip cost rate cannot be negative")
        return cost_rate, cost_profile_version, ()

    if round_trip_cost_rate is not None or cost_profile_version is not None:
        raise ValueError(
            "do not combine external cost inputs with transaction_cost_model"
        )
    estimate = transaction_cost_model.estimate(
        buy_price=entry_open.decimal_price,
        sell_price=exit_close.decimal_price,
        quantity=quantity,
        adv20_ntd=adv20_ntd,
        buy_bid=entry_open.bid,
        buy_ask=entry_open.ask,
        sell_bid=exit_close.bid,
        sell_ask=exit_close.ask,
        horizon=horizon,
    )
    profile = estimate.profile(cost_profile)
    reasons = estimate.reason_codes if not estimate.capacity_pass else ()
    return (
        profile.round_trip_cost_rate,
        profile.cost_profile_version,
        tuple(reasons),
    )
