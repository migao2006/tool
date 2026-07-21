"""Contracts and bounded runtime settings for Fugle adjusted archives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from math import isfinite
import os

from .contracts import IngestionError


def _integer(
    values: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw = values.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _float(
    values: Mapping[str, str],
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    raw = values.get(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error
    if not isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _boolean(values: Mapping[str, str], name: str, default: bool) -> bool:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().casefold()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class FugleAdjustedBackfillSettings:
    """Explicit local request budget; Fugle exposes no quota endpoint here."""

    enabled: bool = False
    request_budget_per_run: int = 25
    pacing_seconds: float = 2.0
    retry_after_seconds: int = 3_600

    @classmethod
    def from_env(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "FugleAdjustedBackfillSettings":
        values = os.environ if environment is None else environment
        return cls(
            enabled=_boolean(values, "FUGLE_ADJUSTED_BACKFILL_ENABLED", False),
            request_budget_per_run=_integer(
                values,
                "FUGLE_ADJUSTED_REQUEST_BUDGET_PER_RUN",
                25,
                minimum=1,
                maximum=100,
            ),
            pacing_seconds=_float(
                values,
                "FUGLE_ADJUSTED_PACING_SECONDS",
                2.0,
                minimum=0.25,
                maximum=60.0,
            ),
            retry_after_seconds=_integer(
                values,
                "FUGLE_ADJUSTED_RETRY_AFTER_SECONDS",
                3_600,
                minimum=60,
                maximum=86_400,
            ),
        )


def _required_int(row: Mapping[str, object], name: str) -> int:
    value = row.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise IngestionError(
            "FUGLE_ADJUSTED_RPC_INVALID",
            f"Fugle adjusted snapshot is missing {name}",
        )
    return value


@dataclass(frozen=True)
class FugleAdjustedBackfillSnapshot:
    task_count: int
    remaining: int
    succeeded: int
    exhausted: int
    archive_object_count: int
    archive_row_count: int
    archive_byte_count: int

    @classmethod
    def from_row(
        cls,
        row: Mapping[str, object],
    ) -> "FugleAdjustedBackfillSnapshot":
        return cls(
            **{
                name: _required_int(row, name)
                for name in (
                    "task_count",
                    "remaining",
                    "succeeded",
                    "exhausted",
                    "archive_object_count",
                    "archive_row_count",
                    "archive_byte_count",
                )
            }
        )


@dataclass(frozen=True)
class FugleAdjustedBackfillSummary:
    outcome: str
    start_date: str
    end_date: str
    attempted_tasks: int
    succeeded_tasks: int
    retried_tasks: int
    fetched_rows: int
    archived_rows: int
    quarantined_rows: int
    configured_request_budget: int
    pacing_seconds: float
    remaining_tasks: int
    exhausted_tasks: int
    archive_object_count: int
    archive_row_count: int
    archive_byte_count: int
    reason_codes: tuple[str, ...]
    system_status: str = "RESEARCH_ONLY"
    usage_scope: str = "RAW_LANDING_ONLY"

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["reason_codes"] = list(self.reason_codes)
        return value
