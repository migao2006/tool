"""Verify and bind archived daily bars and TAIEX OHLC for research assembly."""

# pyright: reportAny=false, reportExplicitAny=false

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, cast, final

from src.data.archive.contracts import HistoricalArchiveManifest
from src.data.archive.historical_parquet_reader import HistoricalParquetReader
from src.data.archive.manifest_repository import HistoricalArchiveManifestSnapshot
from src.data.providers.twse import TAIEX_MONTHLY_OHLC_DATASET
from src.data.research.twse_trading_calendar_snapshot import (
    TwseTradingCalendarSnapshot,
)


DAILY_BAR_FILTERS = {
    "source_dataset": "eq.daily_bars",
    "scheduled_market": "eq.TWSE",
    "asset_type": "eq.COMMON_STOCK",
}
TAIEX_OHLC_FILTERS = {
    "provider_code": "eq.TWSE",
    "source_dataset": f"eq.{TAIEX_MONTHLY_OHLC_DATASET}",
    "scheduled_market": "eq.TWSE",
    "asset_type": "eq.BENCHMARK",
}


class TwseResearchDatasetBuildError(RuntimeError):
    """Stable fail-closed build error without source rows or credentials."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code: str = reason_code


@dataclass(frozen=True)
class VerifiedTwseResearchArchiveInputs:
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


def _manifest(row: Mapping[str, object]) -> HistoricalArchiveManifest:
    return HistoricalArchiveManifest.from_mapping(row)


def _require_complete_snapshot(
    snapshot: HistoricalArchiveManifestSnapshot,
    *,
    missing_code: str,
    incomplete_code: str,
) -> None:
    if not snapshot.complete:
        raise TwseResearchDatasetBuildError(
            incomplete_code,
            "A complete manifest snapshot is required for research assembly",
        )
    if not snapshot.rows:
        raise TwseResearchDatasetBuildError(
            missing_code,
            "The required archive manifest snapshot is empty",
        )


def _validate_daily_manifest(manifest: HistoricalArchiveManifest) -> None:
    if (
        manifest.provider_code != "FINMIND"
        or manifest.source_dataset != "daily_bars"
        or manifest.scheduled_market != "TWSE"
        or manifest.asset_type != "COMMON_STOCK"
    ):
        raise TwseResearchDatasetBuildError(
            "TWSE_DAILY_ARCHIVE_SCOPE_MISMATCH",
            "A daily-bar manifest is outside the frozen TWSE common-stock scope",
        )


def _validate_benchmark_manifest(manifest: HistoricalArchiveManifest) -> None:
    if (
        manifest.provider_code != "TWSE"
        or manifest.source_dataset != TAIEX_MONTHLY_OHLC_DATASET
        or manifest.source_symbol != "TAIEX"
        or manifest.scheduled_market != "TWSE"
        or manifest.asset_type != "BENCHMARK"
    ):
        raise TwseResearchDatasetBuildError(
            "TAIEX_OHLC_ARCHIVE_SCOPE_MISMATCH",
            "A benchmark manifest is outside the official TAIEX OHLC scope",
        )


@final
class TwseResearchArchiveInputLoader:
    """Release rows only after every manifest-bound R2 object is verified."""

    def __init__(self, reader: HistoricalParquetReader) -> None:
        self.reader = reader

    def load(
        self,
        *,
        daily_manifests: HistoricalArchiveManifestSnapshot,
        benchmark_manifests: HistoricalArchiveManifestSnapshot,
        calendar_snapshot: TwseTradingCalendarSnapshot | None,
        feature_rows: Any,
        expected_daily_snapshot_sha256: str,
    ) -> VerifiedTwseResearchArchiveInputs:
        _require_complete_snapshot(
            daily_manifests,
            missing_code="TWSE_DAILY_ARCHIVE_MANIFESTS_MISSING",
            incomplete_code="TWSE_DAILY_ARCHIVE_SNAPSHOT_INCOMPLETE",
        )
        _require_complete_snapshot(
            benchmark_manifests,
            missing_code="TAIEX_OHLC_ARCHIVE_MISSING",
            incomplete_code="TAIEX_OHLC_ARCHIVE_SNAPSHOT_INCOMPLETE",
        )
        if expected_daily_snapshot_sha256 != daily_manifests.snapshot_sha256:
            raise TwseResearchDatasetBuildError(
                "FEATURE_DAILY_ARCHIVE_SNAPSHOT_MISMATCH",
                "Feature and daily-bar artifacts do not use the same manifest snapshot",
            )
        if calendar_snapshot is None:
            raise TwseResearchDatasetBuildError(
                "TRADING_CALENDAR_SNAPSHOT_MISMATCH",
                "A versioned trading-calendar snapshot is required",
            )
        raw_bars, daily_by_key, daily_by_id = self._daily_rows(daily_manifests)
        self._validate_feature_lineage(feature_rows, daily_by_key, daily_by_id)
        benchmark_rows, source_version = self._benchmark_rows(benchmark_manifests)
        benchmark_dates = tuple(
            sorted(cast(date, row["trade_date"]) for row in benchmark_rows)
        )
        if calendar_snapshot.session_dates != benchmark_dates:
            raise TwseResearchDatasetBuildError(
                "TRADING_CALENDAR_SNAPSHOT_MISMATCH",
                "Trading-calendar and TAIEX sessions must match exactly",
            )
        return VerifiedTwseResearchArchiveInputs(
            raw_bars=tuple(raw_bars),
            benchmark_rows=tuple(benchmark_rows),
            daily_manifest_count=daily_manifests.object_count,
            benchmark_manifest_count=benchmark_manifests.object_count,
            benchmark_snapshot_sha256=benchmark_manifests.snapshot_sha256,
            benchmark_source_version=source_version,
            calendar_snapshot_sha256=(
                calendar_snapshot.calendar_snapshot_sha256
            ),
        )

    def _daily_rows(
        self,
        snapshot: HistoricalArchiveManifestSnapshot,
    ) -> tuple[
        list[Mapping[str, object]],
        dict[str, HistoricalArchiveManifest],
        dict[int, HistoricalArchiveManifest],
    ]:
        raw_bars: list[Mapping[str, object]] = []
        by_key: dict[str, HistoricalArchiveManifest] = {}
        by_id: dict[int, HistoricalArchiveManifest] = {}
        for row in snapshot.rows:
            manifest = _manifest(row)
            _validate_daily_manifest(manifest)
            archive_id = row.get("archive_id")
            if isinstance(archive_id, bool) or not isinstance(archive_id, int):
                raise TwseResearchDatasetBuildError(
                    "TWSE_DAILY_ARCHIVE_LINEAGE_INVALID",
                    "A daily-bar manifest is missing its archive identifier",
                )
            if manifest.object_key in by_key or archive_id in by_id:
                raise TwseResearchDatasetBuildError(
                    "TWSE_DAILY_ARCHIVE_LINEAGE_DUPLICATE",
                    "Daily-bar manifest lineage must be unique",
                )
            by_key[manifest.object_key] = manifest
            by_id[archive_id] = manifest
            for raw in self.reader.read(manifest).rows:
                if raw.get("parse_status") == "PARSED":
                    raw_bars.append(
                        {
                            "symbol": manifest.source_symbol,
                            "market": "TWSE",
                            "trade_date": raw.get("trade_date"),
                            "open_price": raw.get("open_price"),
                            "close_price": raw.get("close_price"),
                        }
                    )
        return raw_bars, by_key, by_id

    @staticmethod
    def _validate_feature_lineage(
        feature_rows: Any,
        by_key: Mapping[str, HistoricalArchiveManifest],
        by_id: Mapping[int, HistoricalArchiveManifest],
    ) -> None:
        for feature in feature_rows.itertuples(index=False):
            archive_id = getattr(feature, "archive_id", None)
            object_key = str(getattr(feature, "source_object_key", ""))
            parquet_hash = str(getattr(feature, "source_parquet_sha256", ""))
            payload_hash = str(getattr(feature, "source_payload_sha256", ""))
            symbol = str(getattr(feature, "symbol", "")).strip()
            market = str(getattr(feature, "market", "")).strip().upper()
            asset_type = str(getattr(feature, "asset_type", "")).strip().upper()
            raw_decision_date = getattr(feature, "decision_date", None)
            try:
                decision_date = (
                    raw_decision_date
                    if type(raw_decision_date) is date
                    else date.fromisoformat(str(raw_decision_date)[:10])
                )
            except ValueError:
                decision_date = None
            manifest = by_key.get(object_key)
            if (
                isinstance(archive_id, bool)
                or not isinstance(archive_id, int)
                or manifest is None
                or by_id.get(archive_id) != manifest
                or parquet_hash != manifest.parquet_sha256
                or payload_hash != manifest.source_payload_hash
                or symbol != manifest.source_symbol
                or market != "TWSE"
                or asset_type != "COMMON_STOCK"
                or decision_date is None
                or not (
                    manifest.min_trade_date
                    <= decision_date
                    <= manifest.max_trade_date
                )
            ):
                raise TwseResearchDatasetBuildError(
                    "FEATURE_DAILY_ARCHIVE_LINEAGE_MISMATCH",
                    "A feature row does not match the verified daily-bar manifest",
                )

    def _benchmark_rows(
        self,
        snapshot: HistoricalArchiveManifestSnapshot,
    ) -> tuple[list[Mapping[str, object]], str]:
        rows: list[Mapping[str, object]] = []
        versions: set[str] = set()
        for raw_manifest in snapshot.rows:
            manifest = _manifest(raw_manifest)
            _validate_benchmark_manifest(manifest)
            versions.add(manifest.source_version)
            rows.extend(
                raw
                for raw in self.reader.read(manifest).rows
                if raw.get("parse_status") == "PARSED"
            )
        if len(versions) != 1:
            raise TwseResearchDatasetBuildError(
                "TAIEX_OHLC_SOURCE_VERSION_MIXED",
                "One benchmark snapshot must use exactly one source version",
            )
        dates = [cast(date, row.get("trade_date")) for row in rows]
        duplicates = [value for value, count in Counter(dates).items() if count > 1]
        if not dates or any(type(value) is not date for value in dates):
            raise TwseResearchDatasetBuildError(
                "TAIEX_OHLC_ROWS_MISSING",
                "No valid official TAIEX OHLC rows are available",
            )
        if duplicates:
            raise TwseResearchDatasetBuildError(
                "TAIEX_OHLC_DUPLICATE_SESSION",
                "TAIEX OHLC snapshot contains overlapping trade dates",
            )
        return rows, next(iter(versions))


__all__ = [
    "DAILY_BAR_FILTERS",
    "TAIEX_OHLC_FILTERS",
    "TwseResearchArchiveInputLoader",
    "TwseResearchDatasetBuildError",
    "VerifiedTwseResearchArchiveInputs",
]
