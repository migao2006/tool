"""Market-neutral row adaptation for archive feature artifacts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
import json
from math import isfinite
from types import MappingProxyType
from typing import cast, final
from zoneinfo import ZoneInfo

from src.data.archive.contracts import HistoricalArchiveManifest
from src.data.ingestion.daily_bar_publication import DailyBarPublicationSourceRow
from src.features.price_volume_contracts import PriceVolumeFeatureRow

from .archive_feature_market import (
    ArchiveFeatureMarketProfile,
    archive_feature_market_profile,
)
from .archive_feature_contracts import (
    ArchiveFeatureBuildError,
    CurrentSecurityIdentity,
)
from .daily_bar_publication_snapshot import DailyBarPublicationManifest


TAIPEI = ZoneInfo("Asia/Taipei")
UTC = ZoneInfo("UTC")
DECISION_TIME = time(17, 0)
BUILDER_SOURCE_REASONS = (
    "POINT_IN_TIME_UNVERIFIED",
    "RAW_POINT_IN_TIME_UNVERIFIED",
    "ROW_POINT_IN_TIME_UNVERIFIED",
    "RAW_AVAILABLE_AT_FIRST_OBSERVED_ONLY",
    "BAR_AVAILABLE_AFTER_DECISION",
)


@dataclass(frozen=True)
class SourceProvenance:
    archive_id: int
    object_key: str
    source_payload_sha256: str
    parquet_sha256: str
    source_reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ArchiveRowSource:
    """Verified archive rows prepared by the I/O-owning dataset builder."""

    archive_id: int
    object_key: str
    source_payload_sha256: str
    parquet_sha256: str
    manifest_reason_codes: tuple[str, ...]
    rows: Sequence[Mapping[str, object]]
    row_count: int


@dataclass(frozen=True)
class _AdaptedCanonicalRows:
    records: tuple[dict[str, object], ...]
    provenance_by_date: Mapping[date, SourceProvenance]
    source_row_count: int
    parsed_source_row_count: int
    exclusion_reason_counts: Mapping[str, int]


@dataclass(frozen=True)
class _AdaptedOutputRows:
    rows: tuple[Mapping[str, object], ...]
    exclusion_reason_counts: Mapping[str, int]


def archive_id(values: Mapping[str, object]) -> int:
    value = values.get("archive_id")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ArchiveFeatureBuildError(
            "ARCHIVE_ID_INVALID",
            "Archive manifest contains an invalid archive_id",
        )
    return value


def group_manifests(
    rows: Sequence[Mapping[str, object]],
    *,
    market: str = "TWSE",
) -> dict[str, list[Mapping[str, object]]]:
    return ArchiveFeatureRowAdapter(market=market).group_manifests(rows)


def source_reason_codes(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise ArchiveFeatureBuildError(
            "ARCHIVE_REASON_CODES_INVALID",
            "Archive reason_codes must be canonical JSON",
        )
    try:
        parsed = cast(object, json.loads(value))
    except json.JSONDecodeError as error:
        raise ArchiveFeatureBuildError(
            "ARCHIVE_REASON_CODES_INVALID",
            "Archive reason_codes are not valid JSON",
        ) from error
    if not isinstance(parsed, list):
        raise ArchiveFeatureBuildError(
            "ARCHIVE_REASON_CODES_INVALID",
            "Archive reason_codes are not a string array",
        )
    raw_reasons = cast(list[object], parsed)
    if any(not isinstance(reason, str) or not reason for reason in raw_reasons):
        raise ArchiveFeatureBuildError(
            "ARCHIVE_REASON_CODES_INVALID",
            "Archive reason_codes are not a string array",
        )
    return tuple(dict.fromkeys(cast(list[str], raw_reasons)))


@final
class ArchiveFeatureRowAdapter:
    """Pure market-neutral boundary for source, canonical, and output rows.

    The dataset builder retains verified-object reads, feature calculation,
    writer ownership, and audit assembly. This boundary owns deterministic
    row ordering and selection plus all row-shape adaptations. It is omitted
    from ``__all__`` because it is an internal seam, not a new public API.
    """

    def __init__(self, *, market: str = "TWSE") -> None:
        self.profile: ArchiveFeatureMarketProfile = archive_feature_market_profile(market)

    def group_manifests(
        self,
        rows: Sequence[Mapping[str, object]],
    ) -> dict[str, list[Mapping[str, object]]]:
        grouped: dict[
            str,
            list[tuple[HistoricalArchiveManifest, Mapping[str, object]]],
        ] = {}
        for row in rows:
            manifest = HistoricalArchiveManifest.from_mapping(row)
            if (
                manifest.provider_code != self.profile.provider_code
                or manifest.source_dataset != "daily_bars"
                or manifest.scheduled_market != self.profile.market
                or manifest.asset_type != "COMMON_STOCK"
            ):
                raise ArchiveFeatureBuildError(
                    f"{self.profile.market}_ARCHIVE_SCOPE_MISMATCH",
                    "Archive manifest is outside the requested common-stock scope",
                )
            grouped.setdefault(manifest.source_symbol, []).append((manifest, row))

        ordered: dict[str, list[Mapping[str, object]]] = {}
        for symbol, entries in sorted(grouped.items()):
            entries.sort(
                key=lambda entry: (
                    entry[0].requested_start_date,
                    entry[0].requested_end_date,
                    archive_id(entry[1]),
                )
            )
            for previous, current in zip(entries, entries[1:], strict=False):
                if current[0].requested_start_date <= previous[0].requested_end_date:
                    raise ArchiveFeatureBuildError(
                        f"{self.profile.market}_ARCHIVE_DATE_RANGE_OVERLAP",
                        "One symbol has overlapping archive campaign ranges",
                    )
            ordered[symbol] = [row for _, row in entries]
        return ordered

    def canonical_record(
        self,
        row: Mapping[str, object],
        *,
        identity: CurrentSecurityIdentity,
    ) -> dict[str, object]:
        if (
            identity.market != self.profile.market
            or identity.asset_type != "COMMON_STOCK"
        ):
            raise ArchiveFeatureBuildError(
                f"{self.profile.market}_CURRENT_IDENTITY_SCOPE_MISMATCH",
                "Current identity is outside the requested common-stock scope",
            )
        trade_date = row.get("trade_date")
        if type(trade_date) is not date:
            raise ArchiveFeatureBuildError(
                "PARSED_ARCHIVE_TRADE_DATE_INVALID",
                "Parsed archive row is missing its trade date",
            )
        return {
            "security_id": identity.security_id,
            "listing_period_id": identity.listing_period_id,
            "market": self.profile.market,
            "symbol": identity.symbol,
            "asset_type": "COMMON_STOCK",
            "trade_date": trade_date,
            "decision_at": datetime.combine(trade_date, DECISION_TIME, tzinfo=TAIPEI),
            "available_at": row.get("available_at"),
            "available_at_basis": row.get("available_at_basis"),
            "open_price": row.get("open_price"),
            "high_price": row.get("high_price"),
            "low_price": row.get("low_price"),
            "close_price": row.get("close_price"),
            "trading_volume": row.get("trading_volume"),
            "trading_value": row.get("trading_value"),
            "point_in_time_status": "UNVERIFIED",
            "parse_status": "PARSED",
            # Complete raw reasons remain in output; only the feature builder's
            # frozen first-observed allowlist is supplied after scoped adaptation.
            "reason_codes": BUILDER_SOURCE_REASONS,
        }

    def publication_canonical_record(
        self,
        row: DailyBarPublicationSourceRow,
        *,
        identity: CurrentSecurityIdentity,
    ) -> dict[str, object]:
        """Adapt a verified R2 publication row without claiming PIT verification."""

        if (
            row.market != self.profile.market
            or identity.market != row.market
            or identity.symbol != row.symbol
            or identity.security_id != row.security_id
            or identity.asset_type != "COMMON_STOCK"
        ):
            raise ArchiveFeatureBuildError(
                f"{self.profile.market}_DAILY_PUBLICATION_IDENTITY_MISMATCH",
                "A current daily-bar publication row conflicts with current identity",
            )
        return {
            "security_id": identity.security_id,
            "listing_period_id": identity.listing_period_id,
            "market": row.market,
            "symbol": row.symbol,
            "asset_type": "COMMON_STOCK",
            "trade_date": row.trade_date,
            "decision_at": datetime.combine(
                row.trade_date,
                DECISION_TIME,
                tzinfo=TAIPEI,
            ),
            "available_at": row.available_at,
            "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
            "open_price": row.open_price,
            "high_price": row.high_price,
            "low_price": row.low_price,
            "close_price": row.close_price,
            "trading_volume": row.trading_volume,
            "trading_value": row.trading_value,
            "point_in_time_status": "UNVERIFIED",
            "parse_status": "PARSED",
            # The full publication manifest reasons stay in output provenance.
            # Only the frozen first-observed allowlist participates in feature gates.
            "reason_codes": BUILDER_SOURCE_REASONS,
        }

    def adapt_source_rows(
        self,
        *,
        archive_sources: Sequence[ArchiveRowSource],
        identity: CurrentSecurityIdentity | None,
        publication_row: DailyBarPublicationSourceRow | None = None,
        publication_manifest: DailyBarPublicationManifest | None = None,
        previous: _AdaptedCanonicalRows | None = None,
    ) -> _AdaptedCanonicalRows:
        records = list(previous.records) if previous is not None else []
        provenance_by_date = (
            dict(previous.provenance_by_date) if previous is not None else {}
        )
        exclusion_reasons: Counter[str] = Counter()
        if previous is not None:
            exclusion_reasons.update(previous.exclusion_reason_counts)
        source_row_count = previous.source_row_count if previous is not None else 0
        parsed_source_row_count = (
            previous.parsed_source_row_count if previous is not None else 0
        )

        for source in archive_sources:
            source_row_count += source.row_count
            for row in source.rows:
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
                reasons = tuple(
                    dict.fromkeys(
                        (
                            *source.manifest_reason_codes,
                            *source_reason_codes(row.get("reason_codes")),
                        )
                    )
                )
                provenance_by_date[trade_date] = SourceProvenance(
                    archive_id=source.archive_id,
                    object_key=source.object_key,
                    source_payload_sha256=source.source_payload_sha256,
                    parquet_sha256=source.parquet_sha256,
                    source_reason_codes=reasons,
                )
                records.append(self.canonical_record(row, identity=identity))

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
                provenance_by_date[publication_row.trade_date] = SourceProvenance(
                    archive_id=publication_manifest.publication_snapshot_id,
                    object_key=publication_manifest.object_key,
                    source_payload_sha256=publication_manifest.source_payload_hash,
                    parquet_sha256=publication_manifest.parquet_sha256,
                    source_reason_codes=tuple(
                        dict.fromkeys(
                            (
                                *publication_manifest.reason_codes,
                                "DAILY_BAR_PUBLICATION_RESEARCH_ONLY",
                            )
                        )
                    ),
                )
                records.append(
                    self.publication_canonical_record(
                        publication_row,
                        identity=identity,
                    )
                )

        return _AdaptedCanonicalRows(
            records=tuple(records),
            provenance_by_date=MappingProxyType(dict(provenance_by_date)),
            source_row_count=source_row_count,
            parsed_source_row_count=parsed_source_row_count,
            exclusion_reason_counts=MappingProxyType(
                dict(sorted(exclusion_reasons.items()))
            ),
        )

    def output_row(
        self,
        feature: PriceVolumeFeatureRow,
        *,
        identity: CurrentSecurityIdentity,
        provenance: SourceProvenance,
        dataset_snapshot_sha256: str,
        source_archive_snapshot_sha256: str,
        current_identity_snapshot_sha256: str,
    ) -> dict[str, object]:
        if (
            identity.market != self.profile.market
            or identity.asset_type != "COMMON_STOCK"
            or feature.market != self.profile.market
        ):
            raise ArchiveFeatureBuildError(
                f"{self.profile.market}_FEATURE_ROW_SCOPE_MISMATCH",
                "Feature row is outside the requested common-stock scope",
            )
        if (
            feature.latest_available_at is None
            or feature.latest_observed_available_at is None
            or identity.listing_date is None
        ):
            raise ArchiveFeatureBuildError(
                "ELIGIBLE_FEATURE_PROVENANCE_MISSING",
                "Eligible feature row is missing required provenance",
            )
        values = dict(feature.feature_values)
        if any(value is None for value in values.values()):
            raise ArchiveFeatureBuildError(
                "ELIGIBLE_FEATURE_VALUE_MISSING",
                "Hard-fail feature rows cannot be written",
            )
        decision_close_price = feature.decision_close_price
        if (
            decision_close_price is None
            or not isfinite(decision_close_price)
            or decision_close_price <= 0
        ):
            raise ArchiveFeatureBuildError(
                "ELIGIBLE_DECISION_CLOSE_INVALID",
                "Eligible feature row is missing a finite positive decision close",
            )
        reasons = tuple(
            dict.fromkeys(
                (
                    *self.profile.global_reason_codes,
                    *feature.research_limitation_reason_codes,
                    *provenance.source_reason_codes,
                )
            )
        )
        return {
            "dataset_snapshot_sha256": dataset_snapshot_sha256,
            "source_archive_snapshot_sha256": source_archive_snapshot_sha256,
            "current_identity_snapshot_sha256": current_identity_snapshot_sha256,
            "archive_id": provenance.archive_id,
            "source_object_key": provenance.object_key,
            "source_payload_sha256": provenance.source_payload_sha256,
            "source_parquet_sha256": provenance.parquet_sha256,
            "security_id": feature.security_id,
            "listing_period_id": feature.listing_period_id,
            "symbol": feature.symbol,
            "market": self.profile.market,
            "asset_type": "COMMON_STOCK",
            "listing_date": identity.listing_date,
            "decision_date": feature.decision_date,
            "decision_at": feature.decision_at,
            "horizon": feature.horizon,
            "decision_time_policy_version": self.profile.decision_time_policy_version,
            "feature_schema_version": feature.feature_schema_version,
            "feature_schema_hash": feature.feature_schema_hash,
            "price_basis": feature.price_basis,
            "availability_mode": feature.availability_mode,
            "decision_close_price": decision_close_price,
            "latest_available_at": feature.latest_available_at.astimezone(UTC),
            "latest_observed_available_at": (
                feature.latest_observed_available_at.astimezone(UTC)
            ),
            "point_in_time_audit_pass": feature.point_in_time_audit_pass,
            "hard_fail": False,
            "research_limitation_reason_codes": list(
                feature.research_limitation_reason_codes
            ),
            "hard_fail_reason_codes": [],
            "label_status": "LABELS_NOT_ASSEMBLED",
            "usage_scope": "FEATURE_RESEARCH_ONLY",
            "system_status": "RESEARCH_ONLY",
            "reason_codes": json.dumps(
                reasons,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "source_reason_codes": json.dumps(
                provenance.source_reason_codes,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            **values,
        }

    def adapt_output_rows(
        self,
        features: Sequence[PriceVolumeFeatureRow],
        *,
        identity: CurrentSecurityIdentity,
        provenance_by_date: Mapping[date, SourceProvenance],
        dataset_snapshot_sha256: str,
        source_archive_snapshot_sha256: str,
        current_identity_snapshot_sha256: str,
    ) -> _AdaptedOutputRows:
        rows: list[Mapping[str, object]] = []
        exclusion_reasons: Counter[str] = Counter()
        for feature in features:
            if feature.hard_fail:
                exclusion_reasons.update(feature.hard_fail_reason_codes)
                continue
            provenance = provenance_by_date.get(feature.decision_date)
            if provenance is None:
                raise ArchiveFeatureBuildError(
                    "FEATURE_SOURCE_PROVENANCE_MISSING",
                    "Feature row cannot be linked to its verified archive",
                )
            rows.append(
                self.output_row(
                    feature,
                    identity=identity,
                    provenance=provenance,
                    dataset_snapshot_sha256=dataset_snapshot_sha256,
                    source_archive_snapshot_sha256=source_archive_snapshot_sha256,
                    current_identity_snapshot_sha256=current_identity_snapshot_sha256,
                )
            )
        return _AdaptedOutputRows(
            rows=tuple(rows),
            exclusion_reason_counts=MappingProxyType(
                dict(sorted(exclusion_reasons.items()))
            ),
        )


def canonical_record(
    row: Mapping[str, object],
    *,
    identity: CurrentSecurityIdentity,
    market: str = "TWSE",
) -> dict[str, object]:
    return ArchiveFeatureRowAdapter(market=market).canonical_record(
        row,
        identity=identity,
    )


def publication_canonical_record(
    row: DailyBarPublicationSourceRow,
    *,
    identity: CurrentSecurityIdentity,
) -> dict[str, object]:
    """Adapt a verified R2 publication row without claiming PIT verification."""

    return ArchiveFeatureRowAdapter(market=row.market).publication_canonical_record(
        row,
        identity=identity,
    )


def output_row(
    feature: PriceVolumeFeatureRow,
    *,
    identity: CurrentSecurityIdentity,
    provenance: SourceProvenance,
    dataset_snapshot_sha256: str,
    source_archive_snapshot_sha256: str,
    current_identity_snapshot_sha256: str,
    market: str = "TWSE",
) -> dict[str, object]:
    return ArchiveFeatureRowAdapter(market=market).output_row(
        feature,
        identity=identity,
        provenance=provenance,
        dataset_snapshot_sha256=dataset_snapshot_sha256,
        source_archive_snapshot_sha256=source_archive_snapshot_sha256,
        current_identity_snapshot_sha256=current_identity_snapshot_sha256,
    )


__all__ = [
    "SourceProvenance",
    "archive_id",
    "canonical_record",
    "group_manifests",
    "output_row",
    "publication_canonical_record",
    "source_reason_codes",
]
