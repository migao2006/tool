"""Canonical dynamic no-trade band and three-class label contract."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from math import isfinite, sqrt
from src.core.horizon import PRODUCTION_HORIZON, require_supported_horizon


class DirectionLabel(str, Enum):
    """Tradable direction target derived only from net executable return."""

    UP = "UP"
    NEUTRAL = "NEUTRAL"
    DOWN = "DOWN"


@dataclass(frozen=True)
class NoTradeBandConfig:
    """Validation-selected dynamic no-trade band parameters for one horizon."""

    horizon: int = PRODUCTION_HORIZON
    min_edge_h: float = 0.005
    k_h: float = 0.35
    version: str = "no-trade-band-v1"

    def __post_init__(self) -> None:
        _ = require_supported_horizon(self.horizon)
        if not isfinite(self.min_edge_h) or not isfinite(self.k_h):
            raise ValueError("no-trade band parameters must be finite")
        if self.min_edge_h < 0 or self.k_h < 0:
            raise ValueError("no-trade band parameters must be non-negative")
        if not self.version:
            raise ValueError("no-trade band version is required")


def no_trade_band(trailing_volatility: float, config: NoTradeBandConfig) -> float:
    """Return ``max(min_edge_h, k_h * trailing_volatility * sqrt(h))``."""

    if not isfinite(trailing_volatility) or trailing_volatility < 0:
        raise ValueError("trailing_volatility must be finite and non-negative")
    return max(
        config.min_edge_h,
        config.k_h * trailing_volatility * sqrt(config.horizon),
    )


def make_direction_label(
    net_return: float,
    trailing_volatility: float,
    config: NoTradeBandConfig,
) -> DirectionLabel:
    """Classify net executable return without reusing the rank target."""

    if not isfinite(net_return):
        raise ValueError("net_return must be finite")
    band = no_trade_band(trailing_volatility, config)
    if net_return > band:
        return DirectionLabel.UP
    if net_return < -band:
        return DirectionLabel.DOWN
    return DirectionLabel.NEUTRAL


def make_direction_labels(
    net_returns: Iterable[float],
    trailing_volatilities: Iterable[float],
    config: NoTradeBandConfig,
) -> list[DirectionLabel]:
    returns = list(net_returns)
    volatilities = list(trailing_volatilities)
    if len(returns) != len(volatilities):
        raise ValueError("returns and volatilities must have equal length")
    return [
        make_direction_label(value, volatility, config)
        for value, volatility in zip(returns, volatilities, strict=True)
    ]


__all__ = [
    "DirectionLabel",
    "NoTradeBandConfig",
    "make_direction_label",
    "make_direction_labels",
    "no_trade_band",
]
