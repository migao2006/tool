"""Stream verified venue archives into feature-only research datasets."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from datetime import date, datetime, timezone
from typing import cast

from src.data.archive.historical_parquet_reader import HistoricalParquetReader
from src.data.archive.manifest_repository import HistoricalArchiveManifestSnapshot
from src.features.price_volume_builder import build_price_volume_features

from .archive_feature_market import (
    ArchiveFeatureMarketProfile,
    archive_feature_market_profile,
)
from .archive_feature_contracts import (
    ArchiveFeatureAudit,
    ArchiveFeatureBuildError,
    IdentitySnapshot,
    combined_source_snapshot_hash,
    dataset_snapshot_hash,
)
from .archive_feature_parquet import ArchiveFeatureParquetWriter
from .archive_feature_rows import (
    SourceProvenance,
    archive_id,
    canonical_record,
    group_manifests,
    output_row,
    publication_canonical_record,
    source_reason_codes,
)
from .daily_bar_publication_snapshot import DailyBarPublicationSnapshot


class ArchiveFeatureDatasetBuilder:
    """Verify each object and publish only feature rows that pass hard gates."""

    def __init__(
        self,
        reader: HistoricalParquetReader,
        *,
        market: str = "TWSE",
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.profile: ArchiveFeatureMarketProfile = archive_feature_market_profile(market)
        self.reader: HistoricalParquetReader = reader
        self.now_fn: Callable[[], datetime] = now_fn

    def build(
        self,
        *,
        manifests: HistoricalArchiveManifestSnapshot,
        identities: IdentitySnapshot,
        writer: ArchiveFeatureParquetWriter,
        publication_snapshot: DailyBarPublicationSnapshot | None = None,
    ) -> ArchiveFeatureAudit:
        try:
            if not manifests.complete:
                raise ArchiveFeatureBuildError(
                    "MANIFEST_SNAPSHOT_INCOMPLETE",
                    "A limited manifest sample cannot produce the research dataset",
                )
            if manifests.object_count == 0:
                raise ArchiveFeatureBuildError(
                    f"{self.profile.market}_ARCHIVE_MANIFESTS_EMPTY",
                    "No scoped daily-bar archive manifests were returned",
                )
            if not identities.by_symbol:
                raise ArchiveFeatureBuildError(
                    f"{self.profile.market}_CURRENT_IDENTITIES_EMPTY",
                    "No current common-stock identities were returned",
                )
            if any(
                identity.market != self.profile.market or identity.asset_type != "COMMON_STOCK"
                for identity in identities.by_symbol.values()
            ):
                raise ArchiveFeatureBuildError(
                    f"{self.profile.market}_CURRENT_IDENTITY_SCOPE_MISMATCH",
                    "Current identity snapshot is outside the requested scope",
                )
            grouped = group_manifests(
                manifests.rows,
                market=self.profile.market,
            )
            if (
                publication_snapshot is not None
                and publication_snapshot.manifest.market != self.profile.market
            ):
                raise ArchiveFeatureBuildError(
                    f"{self.profile.market}_DAILY_PUBLICATION_SCOPE_MISMATCH",
                    "The current daily-bar publication belongs to another market",
                )
            source_snapshot_sha256 = combined_source_snapshot_hash(
                historical_archive_snapshot_sha256=manifests.snapshot_sha256,
                publication_snapshot_sha256=(
                    publication_snapshot.manifest.snapshot_sha256
                    if publication_snapshot is not None
                    else None
                ),
            )
            dataset_hash = dataset_snapshot_hash(
                source_archive_snapshot_sha256=source_snapshot_sha256,
                current_identity_snapshot_sha256=identities.snapshot_sha256,
                market=self.profile.market,
            )
        except Exception:
            writer.abort()
            raise
        exclusion_reasons: Counter[str] = Counter()
        verified_archive_count = 0
        source_row_count = 0
        parsed_source_row_count = 0
        output_row_count = 0
        latest_decision_date: date | None = None
        publication_manifest = (
            publication_snapshot.manifest if publication_snapshot is not None else None
        )
        publication_by_symbol = (
            publication_snapshot.by_symbol if publication_snapshot is not None else {}
        )
        try:
            symbols = sorted(set(grouped).union(publication_by_symbol))
            for symbol in symbols:
                symbol_manifests = grouped.get(symbol, [])
                identity = identities.by_symbol.get(symbol)
                records: list[dict[str, object]] = []
                provenance_by_date: dict[date, SourceProvenance] = {}
                for raw_manifest in symbol_manifests:
                    archive = self.reader.read(raw_manifest)
                    verified_archive_count += 1
                    source_row_count += archive.row_count
                    parsed_archive_id = archive_id(raw_manifest)
                    for row in archive.rows:
                        if row.get("parse_status") != "PARSED":
                            exclusion_reasons["ARCHIVE_ROW_QUARANTINED"] += 1
                            continue
                        parsed_source_row_count += 1
                        trade_date = row.get("trade_date")
                        if type(trade_date) is not date:
                            exclusion_reasons["PARSED_ARCHIVE_TRADE_DATE_INVALID"] += 1
                            continue
                        if identity is None:
                            exclusion_reasons["CURRENT_SECURITY_IDENTITY_MISSING"] += 1
                            continue
                        if identity.listing_date is None:
                            exclusion_reasons["CURRENT_IDENTITY_LISTING_DATE_MISSING"] += 1
                            continue
                        if trade_date < identity.listing_date:
                            exclusion_reasons["TRADE_DATE_BEFORE_CURRENT_LISTING_DATE"] += 1
                            continue
                        if (
                            identity.delisting_date is not None
                            and trade_date > identity.delisting_date
                        ):
                            exclusion_reasons["TRADE_DATE_AFTER_CURRENT_DELISTING_DATE"] += 1
                            continue
                        source_reasons = tuple(
                            dict.fromkeys(
                                (
                                    *archive.manifest.reason_codes,
                                    *source_reason_codes(row.get("reason_codes")),
                                )
                            )
                        )
                        provenance_by_date[trade_date] = SourceProvenance(
                            archive_id=parsed_archive_id,
                            object_key=archive.manifest.object_key,
                            source_payload_sha256=archive.manifest.source_payload_hash,
                            parquet_sha256=archive.manifest.parquet_sha256,
                            source_reason_codes=source_reasons,
                        )
                        records.append(
                            canonical_record(
                                row,
                                identity=identity,
                                market=self.profile.market,
                            )
                        )
                publication_row = publication_by_symbol.get(symbol)
                if publication_row is not None:
                    source_row_count += 1
                    parsed_source_row_count += 1
                    if identity is None:
                        exclusion_reasons["CURRENT_SECURITY_IDENTITY_MISSING"] += 1
                    elif identity.listing_date is None:
                        exclusion_reasons["CURRENT_IDENTITY_LISTING_DATE_MISSING"] += 1
                    elif publication_row.trade_date < identity.listing_date:
                        exclusion_reasons["TRADE_DATE_BEFORE_CURRENT_LISTING_DATE"] += 1
                    elif (
                        identity.delisting_date is not None
                        and publication_row.trade_date > identity.delisting_date
                    ):
                        exclusion_reasons["TRADE_DATE_AFTER_CURRENT_DELISTING_DATE"] += 1
                    elif publication_row.trade_date in provenance_by_date:
                        exclusion_reasons["DAILY_PUBLICATION_OVERLAPS_ARCHIVE"] += 1
                    elif publication_manifest is not None:
                        manifest = publication_manifest
                        provenance_by_date[publication_row.trade_date] = SourceProvenance(
                            archive_id=manifest.publication_snapshot_id,
                            object_key=manifest.object_key,
                            source_payload_sha256=manifest.source_payload_hash,
                            parquet_sha256=manifest.parquet_sha256,
                            source_reason_codes=tuple(
                                dict.fromkeys(
                                    (
                                        *manifest.reason_codes,
                                        "DAILY_BAR_PUBLICATION_RESEARCH_ONLY",
                                    )
                                )
                            ),
                        )
                        records.append(
                            publication_canonical_record(
                                publication_row,
                                identity=identity,
                            )
                        )
                if not records or identity is None:
                    continue
                feature_result = build_price_volume_features(
                    records,
                    market=self.profile.market,
                    availability_mode="RESEARCH_SCHEDULING_HINT",
                )
                output_batch: list[Mapping[str, object]] = []
                for feature in feature_result.rows:
                    if feature.hard_fail:
                        exclusion_reasons.update(feature.hard_fail_reason_codes)
                        continue
                    provenance = provenance_by_date.get(feature.decision_date)
                    if provenance is None:
                        raise ArchiveFeatureBuildError(
                            "FEATURE_SOURCE_PROVENANCE_MISSING",
                            "Feature row cannot be linked to its verified archive",
                        )
                    output_batch.append(
                        output_row(
                            feature,
                            identity=identity,
                            provenance=provenance,
                            dataset_snapshot_sha256=dataset_hash,
                            source_archive_snapshot_sha256=source_snapshot_sha256,
                            current_identity_snapshot_sha256=identities.snapshot_sha256,
                            market=self.profile.market,
                        )
                    )
                writer.write_rows(output_batch)
                output_row_count += len(output_batch)
                if output_batch:
                    batch_latest = max(cast(date, row["decision_date"]) for row in output_batch)
                    latest_decision_date = (
                        batch_latest
                        if latest_decision_date is None
                        else max(latest_decision_date, batch_latest)
                    )
            if output_row_count == 0:
                raise ArchiveFeatureBuildError(
                    f"{self.profile.market}_RESEARCH_FEATURE_ROWS_EMPTY",
                    "All archive rows failed the research feature gates",
                )
            audit = ArchiveFeatureAudit(
                generated_at=self.now_fn(),
                dataset_snapshot_sha256=dataset_hash,
                source_archive_snapshot_sha256=source_snapshot_sha256,
                current_identity_snapshot_sha256=identities.snapshot_sha256,
                manifest_count=manifests.object_count,
                manifest_symbol_count=len(grouped),
                current_identity_count=len(identities.by_symbol),
                verified_archive_count=verified_archive_count,
                source_row_count=source_row_count,
                parsed_source_row_count=parsed_source_row_count,
                output_row_count=output_row_count,
                excluded_row_count=max(0, source_row_count - output_row_count),
                exclusion_reason_counts=dict(sorted(exclusion_reasons.items())),
                market=self.profile.market,
                dataset_version=self.profile.dataset_version,
                feature_schema_version=self.profile.feature.schema_version,
                feature_schema_hash=self.profile.feature.schema_hash,
                decision_time_policy_version=(self.profile.decision_time_policy_version),
                reason_codes=self.profile.global_reason_codes,
                historical_archive_snapshot_sha256=manifests.snapshot_sha256,
                publication_snapshot_sha256=(
                    publication_snapshot.manifest.snapshot_sha256
                    if publication_snapshot is not None
                    else None
                ),
                publication_snapshot_id=(
                    publication_snapshot.manifest.publication_snapshot_id
                    if publication_snapshot is not None
                    else None
                ),
                publication_row_count=(
                    publication_snapshot.manifest.row_count
                    if publication_snapshot is not None
                    else 0
                ),
                latest_decision_date=latest_decision_date,
            )
            writer.finish()
        except Exception:
            writer.abort()
            raise
        return audit


__all__ = [
    "ArchiveFeatureBuildError",
    "ArchiveFeatureDatasetBuilder",
]
