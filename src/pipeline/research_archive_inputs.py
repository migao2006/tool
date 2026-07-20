"""Verify venue-scoped daily bars, benchmark OHLC, and feature lineage."""

# pyright: reportAny=false, reportExplicitAny=false

from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from typing import Any, cast

from src.data.archive.historical_parquet_reader import HistoricalParquetReader
from src.data.archive.manifest_repository import HistoricalArchiveManifestSnapshot

from .research_archive_contracts import (
    CalendarSnapshot,
    ResearchArchiveProfile,
    ResearchDatasetBuildError,
    VerifiedResearchArchiveInputs,
)
from .research_archive_rows import ResearchArchiveRowsVerifier


def benchmark_calendar_snapshot_hash(
    *, market: str, benchmark_snapshot_sha256: str, sessions: tuple[date, ...]
) -> str:
    """Version a research-only session list derived from verified benchmark rows."""

    payload = {
        "benchmark_snapshot_sha256": benchmark_snapshot_sha256,
        "calendar_contract": "benchmark-derived-research-sessions.v1",
        "market": market,
        "point_in_time_status": "UNVERIFIED",
        "sessions": [value.isoformat() for value in sessions],
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _require_complete_snapshot(
    snapshot: HistoricalArchiveManifestSnapshot,
    *,
    missing_code: str,
    incomplete_code: str,
) -> None:
    if not snapshot.complete:
        raise ResearchDatasetBuildError(
            incomplete_code,
            "A complete manifest snapshot is required for research assembly",
        )
    if not snapshot.rows:
        raise ResearchDatasetBuildError(
            missing_code,
            "The required archive manifest snapshot is empty",
        )


class ResearchArchiveInputLoader:
    """Release rows only after every manifest-bound R2 object is verified."""

    def __init__(
        self,
        reader: HistoricalParquetReader,
        *,
        profile: ResearchArchiveProfile,
    ) -> None:
        self.reader: HistoricalParquetReader = reader
        self.profile: ResearchArchiveProfile = profile

    def load(
        self,
        *,
        daily_manifests: HistoricalArchiveManifestSnapshot,
        benchmark_manifests: HistoricalArchiveManifestSnapshot,
        calendar_snapshot: CalendarSnapshot | None,
        feature_rows: Any,
        expected_daily_snapshot_sha256: str,
    ) -> VerifiedResearchArchiveInputs:
        market = self.profile.market
        benchmark_prefix = self.profile.benchmark_error_prefix
        _require_complete_snapshot(
            daily_manifests,
            missing_code=f"{market}_DAILY_ARCHIVE_MANIFESTS_MISSING",
            incomplete_code=f"{market}_DAILY_ARCHIVE_SNAPSHOT_INCOMPLETE",
        )
        _require_complete_snapshot(
            benchmark_manifests,
            missing_code=f"{benchmark_prefix}_ARCHIVE_MISSING",
            incomplete_code=f"{benchmark_prefix}_ARCHIVE_SNAPSHOT_INCOMPLETE",
        )
        if expected_daily_snapshot_sha256 != daily_manifests.snapshot_sha256:
            raise ResearchDatasetBuildError(
                "FEATURE_DAILY_ARCHIVE_SNAPSHOT_MISMATCH",
                "Feature and daily-bar artifacts do not use the same manifest snapshot",
            )
        verifier = ResearchArchiveRowsVerifier(self.reader, profile=self.profile)
        raw_bars, daily_by_key, daily_by_id = verifier.daily_rows(daily_manifests)
        verifier.validate_feature_lineage(feature_rows, daily_by_key, daily_by_id)
        benchmark_rows, source_version = verifier.benchmark_rows(benchmark_manifests)
        benchmark_dates = tuple(
            sorted(cast(date, row["trade_date"]) for row in benchmark_rows)
        )
        if self.profile.calendar_policy == "EXTERNAL":
            if calendar_snapshot is None or (
                calendar_snapshot.session_dates != benchmark_dates
            ):
                raise ResearchDatasetBuildError(
                    "TRADING_CALENDAR_SNAPSHOT_MISMATCH",
                    "Trading-calendar and benchmark sessions must match exactly",
                )
            calendar_hash = calendar_snapshot.calendar_snapshot_sha256
        else:
            if calendar_snapshot is not None:
                raise ResearchDatasetBuildError(
                    "TPEX_TRADING_CALENDAR_CALLER_ASSERTION_REJECTED",
                    "TPEX research sessions must be derived from verified benchmark bytes",
                )
            calendar_hash = benchmark_calendar_snapshot_hash(
                market=market,
                benchmark_snapshot_sha256=benchmark_manifests.snapshot_sha256,
                sessions=benchmark_dates,
            )
        return VerifiedResearchArchiveInputs(
            raw_bars=tuple(raw_bars),
            benchmark_rows=tuple(benchmark_rows),
            daily_manifest_count=daily_manifests.object_count,
            benchmark_manifest_count=benchmark_manifests.object_count,
            benchmark_snapshot_sha256=benchmark_manifests.snapshot_sha256,
            benchmark_source_version=source_version,
            calendar_snapshot_sha256=calendar_hash,
        )

__all__ = [
    "CalendarSnapshot",
    "ResearchArchiveInputLoader",
    "ResearchArchiveProfile",
    "ResearchDatasetBuildError",
    "VerifiedResearchArchiveInputs",
    "benchmark_calendar_snapshot_hash",
]
