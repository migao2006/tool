"""Validate manifest scope, R2 rows, and feature-to-archive lineage."""

# pyright: reportAny=false, reportExplicitAny=false

from __future__ import annotations

from calendar import monthrange
from collections import Counter
from collections.abc import Mapping
from datetime import date
from typing import Any, cast, final

from src.data.archive.contracts import HistoricalArchiveManifest
from src.data.archive.historical_parquet_reader import HistoricalParquetReader
from src.data.archive.manifest_repository import HistoricalArchiveManifestSnapshot

from .research_archive_contracts import (
    ResearchArchiveProfile,
    ResearchDatasetBuildError,
)


def _month_after(value: tuple[int, int]) -> tuple[int, int]:
    year, month = value
    return (year + 1, 1) if month == 12 else (year, month + 1)


@final
class ResearchArchiveRowsVerifier:
    """Read only exact venue-scoped manifests and verify every feature lineage."""

    def __init__(
        self,
        reader: HistoricalParquetReader,
        *,
        profile: ResearchArchiveProfile,
    ) -> None:
        self.reader = reader
        self.profile = profile

    def daily_rows(
        self, snapshot: HistoricalArchiveManifestSnapshot
    ) -> tuple[
        list[Mapping[str, object]],
        dict[str, HistoricalArchiveManifest],
        dict[int, HistoricalArchiveManifest],
    ]:
        raw_bars: list[Mapping[str, object]] = []
        by_key: dict[str, HistoricalArchiveManifest] = {}
        by_id: dict[int, HistoricalArchiveManifest] = {}
        for row in snapshot.rows:
            manifest = HistoricalArchiveManifest.from_mapping(row)
            self._validate_daily_manifest(manifest)
            archive_id = row.get("archive_id")
            if isinstance(archive_id, bool) or not isinstance(archive_id, int):
                raise ResearchDatasetBuildError(
                    f"{self.profile.market}_DAILY_ARCHIVE_LINEAGE_INVALID",
                    "A daily-bar manifest is missing its archive identifier",
                )
            if manifest.object_key in by_key or archive_id in by_id:
                raise ResearchDatasetBuildError(
                    f"{self.profile.market}_DAILY_ARCHIVE_LINEAGE_DUPLICATE",
                    "Daily-bar manifest lineage must be unique",
                )
            by_key[manifest.object_key] = manifest
            by_id[archive_id] = manifest
            for raw in self.reader.read(manifest).rows:
                if raw.get("parse_status") == "PARSED":
                    raw_bars.append(
                        {
                            "symbol": manifest.source_symbol,
                            "market": self.profile.market,
                            "trade_date": raw.get("trade_date"),
                            "open_price": raw.get("open_price"),
                            "close_price": raw.get("close_price"),
                        }
                    )
        return raw_bars, by_key, by_id

    def validate_feature_lineage(
        self,
        feature_rows: Any,
        by_key: Mapping[str, HistoricalArchiveManifest],
        by_id: Mapping[int, HistoricalArchiveManifest],
    ) -> None:
        for feature in feature_rows.itertuples(index=False):
            archive_id = getattr(feature, "archive_id", None)
            object_key = str(getattr(feature, "source_object_key", ""))
            raw_date = getattr(feature, "decision_date", None)
            try:
                decision_date = (
                    raw_date
                    if type(raw_date) is date
                    else date.fromisoformat(str(raw_date)[:10])
                )
            except ValueError:
                decision_date = None
            manifest = by_key.get(object_key)
            if (
                isinstance(archive_id, bool)
                or not isinstance(archive_id, int)
                or manifest is None
                or by_id.get(archive_id) != manifest
                or str(getattr(feature, "source_parquet_sha256", ""))
                != manifest.parquet_sha256
                or str(getattr(feature, "source_payload_sha256", ""))
                != manifest.source_payload_hash
                or str(getattr(feature, "symbol", "")).strip()
                != manifest.source_symbol
                or str(getattr(feature, "market", "")).strip().upper()
                != self.profile.market
                or str(getattr(feature, "asset_type", "")).strip().upper()
                != "COMMON_STOCK"
                or decision_date is None
                or not (
                    manifest.min_trade_date
                    <= decision_date
                    <= manifest.max_trade_date
                )
            ):
                raise ResearchDatasetBuildError(
                    "FEATURE_DAILY_ARCHIVE_LINEAGE_MISMATCH",
                    "A feature row does not match the verified daily-bar manifest",
                )

    def benchmark_rows(
        self, snapshot: HistoricalArchiveManifestSnapshot
    ) -> tuple[list[Mapping[str, object]], str]:
        rows: list[Mapping[str, object]] = []
        versions: set[str] = set()
        months: list[tuple[int, int]] = []
        for raw_manifest in snapshot.rows:
            manifest = HistoricalArchiveManifest.from_mapping(raw_manifest)
            self._validate_benchmark_manifest(manifest)
            versions.add(manifest.source_version)
            if self.profile.calendar_policy == "BENCHMARK_DERIVED":
                expected_end = manifest.requested_start_date.replace(
                    day=monthrange(
                        manifest.requested_start_date.year,
                        manifest.requested_start_date.month,
                    )[1]
                )
                if (
                    manifest.requested_start_date.day != 1
                    or manifest.requested_end_date != expected_end
                ):
                    raise ResearchDatasetBuildError(
                        "TPEX_OHLC_MONTH_SCOPE_INVALID",
                        "TPEX benchmark manifests must represent complete months",
                    )
                months.append(
                    (
                        manifest.requested_start_date.year,
                        manifest.requested_start_date.month,
                    )
                )
            rows.extend(
                raw
                for raw in self.reader.read(manifest).rows
                if raw.get("parse_status") == "PARSED"
            )
        prefix = self.profile.benchmark_error_prefix
        if len(versions) != 1:
            raise ResearchDatasetBuildError(
                f"{prefix}_SOURCE_VERSION_MIXED",
                "One benchmark snapshot must use exactly one source version",
            )
        self._validate_months(months)
        dates = [row.get("trade_date") for row in rows]
        if not dates or any(type(value) is not date for value in dates):
            raise ResearchDatasetBuildError(
                f"{prefix}_ROWS_MISSING",
                "No valid official benchmark OHLC rows are available",
            )
        typed_dates = cast(list[date], dates)
        if any(count > 1 for count in Counter(typed_dates).values()):
            raise ResearchDatasetBuildError(
                f"{prefix}_DUPLICATE_SESSION",
                "Benchmark OHLC snapshot contains overlapping trade dates",
            )
        return rows, next(iter(versions))

    def _validate_daily_manifest(self, manifest: HistoricalArchiveManifest) -> None:
        if (
            manifest.provider_code != "FINMIND"
            or manifest.source_dataset != "daily_bars"
            or manifest.scheduled_market != self.profile.market
            or manifest.asset_type != "COMMON_STOCK"
        ):
            raise ResearchDatasetBuildError(
                f"{self.profile.market}_DAILY_ARCHIVE_SCOPE_MISMATCH",
                "A daily-bar manifest is outside the frozen market scope",
            )

    def _validate_benchmark_manifest(
        self, manifest: HistoricalArchiveManifest
    ) -> None:
        profile = self.profile
        if (
            manifest.provider_code != profile.benchmark_provider
            or manifest.source_dataset != profile.benchmark_dataset
            or manifest.source_symbol != profile.benchmark_symbol
            or manifest.scheduled_market != profile.market
            or manifest.asset_type != "BENCHMARK"
        ):
            raise ResearchDatasetBuildError(
                f"{profile.benchmark_error_prefix}_ARCHIVE_SCOPE_MISMATCH",
                "A benchmark manifest is outside its frozen official scope",
            )

    @staticmethod
    def _validate_months(months: list[tuple[int, int]]) -> None:
        if not months:
            return
        ordered = sorted(months)
        if len(set(ordered)) != len(ordered) or any(
            following != _month_after(current)
            for current, following in zip(ordered, ordered[1:], strict=False)
        ):
            raise ResearchDatasetBuildError(
                "TPEX_OHLC_MONTH_COVERAGE_GAP",
                "TPEX benchmark manifest months must be unique and contiguous",
            )


__all__ = ["ResearchArchiveRowsVerifier"]
