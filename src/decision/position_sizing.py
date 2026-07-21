"""Volatility/capacity sizing after rank-only candidate selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class PositionLimits:
    maximum_single_name_weight: float = 0.10
    maximum_industry_weight: float = 0.25
    maximum_adv_participation: float = 0.01

    def __post_init__(self) -> None:
        for value in (
            self.maximum_single_name_weight,
            self.maximum_industry_weight,
            self.maximum_adv_participation,
        ):
            if not 0 < value <= 1:
                raise ValueError("position limits must lie in (0, 1]")


def allocate_inverse_volatility(
    candidates: Iterable[Mapping[str, object]],
    portfolio_equity: float,
    market_exposure_cap: float,
    limits: PositionLimits | None = None,
) -> dict[str, float]:
    """Return weights without changing ordering or creating a final score."""

    limits = limits or PositionLimits()
    if portfolio_equity <= 0 or not 0 <= market_exposure_cap <= 1:
        raise ValueError("portfolio equity and market exposure must be valid")
    rows = list(candidates)
    if not rows or market_exposure_cap == 0:
        return {}
    if any(float(row["forecast_volatility"]) <= 0 for row in rows):
        raise ValueError("forecast volatility must be positive for every candidate")
    inverse_volatility = {
        str(row["symbol"]): 1.0 / float(row["forecast_volatility"]) for row in rows
    }
    total = sum(inverse_volatility.values())
    weights: dict[str, float] = {}
    industry_used: dict[str, float] = {}
    for row in rows:
        symbol = str(row["symbol"])
        industry = str(row.get("industry", "UNKNOWN"))
        unconstrained = market_exposure_cap * inverse_volatility[symbol] / total
        adv_value = row.get("adv20_ntd", row.get("adv20"))
        if adv_value is None or float(adv_value) <= 0:
            raise ValueError("ADV20 NTD must be positive for every candidate")
        adv_limit = float(adv_value) * limits.maximum_adv_participation / portfolio_equity
        industry_room = max(0.0, limits.maximum_industry_weight - industry_used.get(industry, 0.0))
        weight = max(0.0, min(unconstrained, limits.maximum_single_name_weight, adv_limit, industry_room))
        weights[symbol] = weight
        industry_used[industry] = industry_used.get(industry, 0.0) + weight
    return weights
