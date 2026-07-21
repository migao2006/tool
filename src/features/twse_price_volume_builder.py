"""Backward-compatible TWSE entry point for shared price/volume features."""

from .price_volume_builder import build_twse_price_volume_features

__all__ = ["build_twse_price_volume_features"]
