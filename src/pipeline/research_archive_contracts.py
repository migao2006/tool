"""Typed contracts shared by venue-scoped research archive readers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Protocol


class ResearchDatasetBuildError(RuntimeError):
    """Stable fail-closed build error without source rows or credentials."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code: str = reason_code


class CalendarSnapshot(Protocol):
    @property
    def session_dates(self) -> tuple[date, ...]: ...

    @property
    def calendar_snapshot_sha256(self) -> str: ...


@dataclass(frozen=True)
class ResearchArchiveProfile:
    market: str
    benchmark_provider: str
    benchmark_dataset: str
    benchmark_symbol: str
    benchmark_error_prefix: str
    calendar_policy: str

    def __post_init__(self) -> None:
        if self.market not in {"TWSE", "TPEX"}:
            raise ValueError("archive profile market is unsupported")
        if self.calendar_policy not in {"EXTERNAL", "BENCHMARK_DERIVED"}:
            raise ValueError("archive profile calendar policy is unsupported")

    @property
    def daily_filters(self) -> Mapping[str, str]:
        return {
            "provider_code": "eq.FINMIND",
            "source_dataset": "eq.daily_bars",
            "scheduled_market": f"eq.{self.market}",
            "asset_type": "eq.COMMON_STOCK",
        }

    @property
    def benchmark_filters(self) -> Mapping[str, str]:
        return {
            "provider_code": f"eq.{self.benchmark_provider}",
            "source_dataset": f"eq.{self.benchmark_dataset}",
            "scheduled_market": f"eq.{self.market}",
            "asset_type": "eq.BENCHMARK",
            "source_symbol": f"eq.{self.benchmark_symbol}",
        }


@dataclass(frozen=True)
class VerifiedResearchArchiveInputs:
    raw_bars: tuple[Mapping[str, object], ...]
    benchmark_rows: tuple[Mapping[str, object], ...]
    daily_manifest_count: int
    benchmark_manifest_count: int
    benchmark_snapshot_sha256: str
    benchmark_source_version: str
    calendar_snapshot_sha256: str

    def __post_init__(self) -> None:
        counts = (
            len(self.raw_bars),
            len(self.benchmark_rows),
            self.daily_manifest_count,
            self.benchmark_manifest_count,
        )
        if any(value <= 0 for value in counts):
            raise ValueError("verified archive inputs must be non-empty")
        if any(
            len(value) != 64
            for value in (
                self.benchmark_snapshot_sha256,
                self.calendar_snapshot_sha256,
            )
        ):
            raise ValueError("archive input snapshot SHA-256 is invalid")


__all__ = [
    "CalendarSnapshot",
    "ResearchArchiveProfile",
    "ResearchDatasetBuildError",
    "VerifiedResearchArchiveInputs",
]
