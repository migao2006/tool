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


def _storage_target(environment: Mapping[str, str]) -> str:
    value = environment.get("HISTORICAL_BACKFILL_STORAGE_TARGET", "SUPABASE")
    normalized = value.strip().upper()
    if normalized not in {"SUPABASE", "R2"}:
        raise ValueError("HISTORICAL_BACKFILL_STORAGE_TARGET must be SUPABASE or R2")
    return normalized


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
    storage_target: str = "SUPABASE"
    max_archive_objects_per_run: int = 100
    max_archive_object_bytes: int = 50_000_000

    @classmethod
    def from_env(
        cls, environment: Mapping[str, str] | None = None
    ) -> "HistoricalBackfillSettings":
        values = os.environ if environment is None else environment
        return cls(
            quota_reserve=_integer(values, "FINMIND_QUOTA_RESERVE", 20, 0, 500),
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
            storage_target=_storage_target(values),
            max_archive_objects_per_run=_integer(
                values,
                "HISTORICAL_BACKFILL_MAX_ARCHIVE_OBJECTS_PER_RUN",
                100,
                1,
                100,
            ),
            max_archive_object_bytes=_integer(
                values,
                "HISTORICAL_BACKFILL_MAX_ARCHIVE_OBJECT_BYTES",
                50_000_000,
                1_000_000,
                500_000_000,
            ),
        )

    def __post_init__(self) -> None:
        if self.pacing_floor_seconds < 0:
            raise ValueError("pacing_floor_seconds must not be negative")
        if not 1 <= self.storage_safety_factor <= 5:
            raise ValueError("storage_safety_factor must be between 1 and 5")
        if self.storage_target not in {"SUPABASE", "R2"}:
            raise ValueError("storage_target must be SUPABASE or R2")
