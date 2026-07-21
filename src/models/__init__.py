"""Model contracts for the five-trading-day MVP."""

from ..core.horizon import PRODUCTION_HORIZON, require_supported_horizon
from .metadata import ModelMetadata

__all__ = ["ModelMetadata", "PRODUCTION_HORIZON", "require_supported_horizon"]
