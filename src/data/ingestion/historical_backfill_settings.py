"""Validated runtime limits for scheduled historical backfills."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os


def _integer(
    environment: Mapping[str, str], name: str, default: int, minimum: int, maximum: int
) -> int:
    raw = environment.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class HistoricalBackfillSettings:
    quota_reserve: int = 20
    max_runtime_seconds: int = 1_200
    max_database_bytes: int = 420_000_000
    minimum_symbol_bytes: int = 2_500_000
    lease_seconds: int = 1_800
    retry_after_seconds: int = 900
    pacing_floor_seconds: float = 6.5
    storage_safety_factor: float = 1.25

    @classmethod
    def from_env(
        cls, environment: Mapping[str, str] | None = None
    ) -> "HistoricalBackfillSettings":
        values = os.environ if environment is None else environment
        return cls(
            quota_reserve=_integer(
                values, "FINMIND_QUOTA_RESERVE", 20, 0, 500
            ),
            max_runtime_seconds=_integer(
                values,
                "HISTORICAL_BACKFILL_MAX_RUNTIME_SECONDS",
                1_200,
                60,
                3_300,
            ),
            max_database_bytes=_integer(
                values,
                "HISTORICAL_BACKFILL_MAX_DATABASE_BYTES",
                420_000_000,
                50_000_000,
                500_000_000,
            ),
            minimum_symbol_bytes=_integer(
                values,
                "HISTORICAL_BACKFILL_MINIMUM_SYMBOL_BYTES",
                2_500_000,
                100_000,
                20_000_000,
            ),
        )

    def __post_init__(self) -> None:
        if self.pacing_floor_seconds < 0:
            raise ValueError("pacing_floor_seconds must not be negative")
        if not 1 <= self.storage_safety_factor <= 5:
            raise ValueError("storage_safety_factor must be between 1 and 5")
