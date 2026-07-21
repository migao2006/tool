"""Compatibility aliases for the canonical horizon contract."""

from ..core.horizon import PRODUCTION_HORIZON, require_supported_horizon

validate_horizon = require_supported_horizon

__all__ = ["PRODUCTION_HORIZON", "validate_horizon"]
