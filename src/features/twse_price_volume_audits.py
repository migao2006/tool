"""Backward-compatible TWSE import path for shared feature audits."""

from .price_volume_audits import build_feature_audits

__all__ = ["build_feature_audits"]
