from __future__ import annotations

SUPPORTED_HORIZONS = (2, 3, 5, 10)
PRODUCTION_HORIZON = 5


def require_supported_horizon(horizon: int) -> int:
    """Validate an interface horizon without enabling it for production."""
    if horizon not in SUPPORTED_HORIZONS:
        raise ValueError(
            f"Unsupported horizon={horizon}; expected one of {SUPPORTED_HORIZONS}."
        )
    return horizon


def require_production_horizon(horizon: int) -> int:
    """Reject unfinished model horizons in production entry points."""
    require_supported_horizon(horizon)
    if horizon != PRODUCTION_HORIZON:
        raise NotImplementedError(
            f"horizon={horizon} is reserved for a separate future model; "
            f"only horizon={PRODUCTION_HORIZON} is production-enabled."
        )
    return horizon

