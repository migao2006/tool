"""Build one TPEX feature delta from verified history and daily DB revisions."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Protocol, cast

from src.data.archive.contracts import HistoricalArchiveManifest
from src.data.archive.historical_parquet_reader import HistoricalParquetReader
from src.data.archive.manifest_repository import HistoricalArchiveManifestSnapshot
from src.features.price_volume_builder import build_price_volume_features
from .archive_feature_contracts import IdentitySnapshot
from .archive_feature_rows import (
    SourceProvenance,
    archive_id,
    canonical_record,
    group_manifests,
    source_reason_codes,
)
from .tpex_daily_bar_contracts import (
    TpexDailyBar,
    TpexDailyBarSeriesSnapshot,
)
from .tpex_daily_feature_delta_contracts import (
    TpexDailyFeatureDeltaAudit,
    TpexDailyFeatureDeltaError,
    daily_feature_delta_snapshot_hash,
)
from .tpex_daily_feature_delta_rows import daily_record, delta_output_row


class DeltaRowWriter(Protocol):
    def write_rows(self, rows: Sequence[Mapping[str, object]]) -> None: ...

    def finish(self) -> None: ...

    def abort(self) -> None: ...


def daily_delta_start_date(manifests: HistoricalArchiveManifestSnapshot) -> date:
    if not manifests.complete or not manifests.rows:
        raise TpexDailyFeatureDeltaError(
            "TPEX_DAILY_FEATURE_DELTA_ARCHIVE_SNAPSHOT_INVALID",
            "A complete TPEX archive snapshot is required",
        )
    maximum_dates = tuple(
        HistoricalArchiveManifest.from_mapping(row).max_trade_date
        for row in manifests.rows
    )
    return min(maximum_dates) + timedelta(days=1)


class TpexDailyFeatureDeltaBuilder:
    def __init__(
        self,
        reader: HistoricalParquetReader,
        *,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.reader = reader
        self.now_fn = now_fn

    def build(
        self,
        *,
        manifests: HistoricalArchiveManifestSnapshot,
        identities: IdentitySnapshot,
        daily_bars: TpexDailyBarSeriesSnapshot,
        writer: DeltaRowWriter,
    ) -> TpexDailyFeatureDeltaAudit:
        try:
            grouped = group_manifests(manifests.rows, market="TPEX")
            if not identities.by_symbol:
                raise self._error(
                    "IDENTITIES_EMPTY", "Current TPEX identities are unavailable"
                )
            max_archive_date = max(
                HistoricalArchiveManifest.from_mapping(row).max_trade_date
                for row in manifests.rows
            )
            if daily_bars.as_of_date <= max_archive_date:
                raise self._error(
                    "NOT_NEWER_THAN_ARCHIVE",
                    "Daily feature delta does not extend the historical archive",
                )
            dataset_hash = daily_feature_delta_snapshot_hash(
                source_archive_snapshot_sha256=manifests.snapshot_sha256,
                current_identity_snapshot_sha256=identities.snapshot_sha256,
                daily_bar_snapshot_sha256=daily_bars.snapshot_sha256,
                as_of_date=daily_bars.as_of_date,
            )
        except Exception:
            writer.abort()
            raise

        target_revision = daily_bars.revisions[-1]
        target_by_id = target_revision.by_security_id
        daily_by_security: dict[int, list[TpexDailyBar]] = {}
        for revision in daily_bars.revisions:
            for row in revision.rows:
                daily_by_security.setdefault(row.security_id, []).append(row)

        exclusion_reasons: Counter[str] = Counter()
        output_rows: list[Mapping[str, object]] = []
        verified_archive_count = 0
        try:
            for symbol, symbol_manifests in grouped.items():
                identity = identities.by_symbol.get(symbol)
                records: list[dict[str, object]] = []
                history_lineage: SourceProvenance | None = None
                last_history_date: date | None = None
                for raw_manifest in symbol_manifests:
                    archive = self.reader.read(raw_manifest)
                    verified_archive_count += 1
                    parsed_archive_id = archive_id(raw_manifest)
                    for source_row in archive.rows:
                        if source_row.get("parse_status") != "PARSED":
                            continue
                        trade_date = source_row.get("trade_date")
                        if type(trade_date) is not date or identity is None:
                            continue
                        if (
                            identity.listing_date is None
                            or trade_date < identity.listing_date
                        ):
                            continue
                        if (
                            identity.delisting_date
                            and trade_date > identity.delisting_date
                        ):
                            continue
                        records.append(
                            canonical_record(
                                source_row, identity=identity, market="TPEX"
                            )
                        )
                        if last_history_date is None or trade_date > last_history_date:
                            last_history_date = trade_date
                            history_lineage = SourceProvenance(
                                archive_id=parsed_archive_id,
                                object_key=archive.manifest.object_key,
                                source_payload_sha256=(
                                    archive.manifest.source_payload_hash
                                ),
                                parquet_sha256=archive.manifest.parquet_sha256,
                                source_reason_codes=tuple(
                                    dict.fromkeys(
                                        (
                                            *archive.manifest.reason_codes,
                                            *source_reason_codes(
                                                source_row.get("reason_codes")
                                            ),
                                        )
                                    )
                                ),
                            )
                if (
                    identity is None
                    or history_lineage is None
                    or last_history_date is None
                ):
                    continue
                target = target_by_id.get(identity.security_id)
                if target is None:
                    continue
                for daily in daily_by_security.get(identity.security_id, ()):
                    if daily.trade_date > last_history_date:
                        records.append(daily_record(daily, identity))
                records.sort(key=lambda record: cast(date, record["trade_date"]))
                sessions = tuple(
                    sorted(
                        {cast(date, record["trade_date"]) for record in records}
                        | {revision.as_of_date for revision in daily_bars.revisions}
                    )
                )
                features = build_price_volume_features(
                    records[-61:],
                    market="TPEX",
                    trading_sessions=sessions[-61:],
                    availability_mode="RESEARCH_SCHEDULING_HINT",
                )
                target_features = tuple(
                    feature
                    for feature in features.rows
                    if feature.decision_date == daily_bars.as_of_date
                )
                if len(target_features) != 1:
                    exclusion_reasons["TARGET_FEATURE_ROW_MISSING"] += 1
                    continue
                feature = target_features[0]
                if feature.hard_fail:
                    exclusion_reasons.update(feature.hard_fail_reason_codes)
                    continue
                output_rows.append(
                    delta_output_row(
                        feature,
                        identity=identity,
                        history=history_lineage,
                        daily=target,
                        dataset_snapshot_sha256=dataset_hash,
                        source_archive_snapshot_sha256=manifests.snapshot_sha256,
                        current_identity_snapshot_sha256=identities.snapshot_sha256,
                        daily_bar_snapshot_sha256=daily_bars.snapshot_sha256,
                    )
                )
            if verified_archive_count != manifests.object_count:
                raise self._error(
                    "ARCHIVE_VERIFICATION_INCOMPLETE",
                    "Every scoped historical archive must be verified",
                )
            if not output_rows:
                raise self._error("ROWS_EMPTY", "All TPEX daily feature rows failed")
            writer.write_rows(output_rows)
            writer.finish()
        except Exception:
            writer.abort()
            raise
        return TpexDailyFeatureDeltaAudit(
            generated_at=self.now_fn(),
            as_of_date=daily_bars.as_of_date,
            dataset_snapshot_sha256=dataset_hash,
            source_archive_snapshot_sha256=manifests.snapshot_sha256,
            current_identity_snapshot_sha256=identities.snapshot_sha256,
            daily_bar_snapshot_sha256=daily_bars.snapshot_sha256,
            manifest_count=manifests.object_count,
            daily_source_row_count=daily_bars.row_count,
            verified_archive_count=verified_archive_count,
            output_row_count=len(output_rows),
            excluded_row_count=max(0, len(target_revision.rows) - len(output_rows)),
            exclusion_reason_counts=dict(sorted(exclusion_reasons.items())),
        )

    @staticmethod
    def _error(suffix: str, message: str) -> TpexDailyFeatureDeltaError:
        return TpexDailyFeatureDeltaError(f"TPEX_DAILY_FEATURE_DELTA_{suffix}", message)


__all__ = ["TpexDailyFeatureDeltaBuilder", "daily_delta_start_date"]
