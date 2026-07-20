"""Market-neutral row adaptation for archive feature artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
import json
from math import isfinite
from typing import cast
from zoneinfo import ZoneInfo

from src.data.archive.contracts import HistoricalArchiveManifest
from src.features.price_volume_contracts import PriceVolumeFeatureRow

from .archive_feature_market import (
    ArchiveFeatureMarketProfile,
    archive_feature_market_profile,
)
from .archive_feature_contracts import (
    ArchiveFeatureBuildError,
    CurrentSecurityIdentity,
)



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
    profile = archive_feature_market_profile(market)
    grouped: dict[
        str, list[tuple[HistoricalArchiveManifest, Mapping[str, object]]]
    ] = {}
    for row in rows:
        manifest = HistoricalArchiveManifest.from_mapping(row)
        if (
            manifest.provider_code != profile.provider_code
            or manifest.source_dataset != "daily_bars"
            or manifest.scheduled_market != profile.market
            or manifest.asset_type != "COMMON_STOCK"
        ):
            raise ArchiveFeatureBuildError(
                f"{profile.market}_ARCHIVE_SCOPE_MISMATCH",
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
                    f"{profile.market}_ARCHIVE_DATE_RANGE_OVERLAP",
                    "One symbol has overlapping archive campaign ranges",
                )
        ordered[symbol] = [row for _, row in entries]
    return ordered


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


def canonical_record(
    row: Mapping[str, object],
    *,
    identity: CurrentSecurityIdentity,
    market: str = "TWSE",
) -> dict[str, object]:
    profile = archive_feature_market_profile(market)
    if identity.market != profile.market or identity.asset_type != "COMMON_STOCK":
        raise ArchiveFeatureBuildError(
            f"{profile.market}_CURRENT_IDENTITY_SCOPE_MISMATCH",
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
        "market": profile.market,
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
    profile: ArchiveFeatureMarketProfile = archive_feature_market_profile(market)
    if (
        identity.market != profile.market
        or identity.asset_type != "COMMON_STOCK"
        or feature.market != profile.market
    ):
        raise ArchiveFeatureBuildError(
            f"{profile.market}_FEATURE_ROW_SCOPE_MISMATCH",
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
                *profile.global_reason_codes,
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
        "market": profile.market,
        "asset_type": "COMMON_STOCK",
        "listing_date": identity.listing_date,
        "decision_date": feature.decision_date,
        "decision_at": feature.decision_at,
        "horizon": feature.horizon,
        "decision_time_policy_version": profile.decision_time_policy_version,
        "feature_schema_version": feature.feature_schema_version,
        "feature_schema_hash": feature.feature_schema_hash,
        "price_basis": feature.price_basis,
        "availability_mode": feature.availability_mode,
        "decision_close_price": decision_close_price,
        "latest_available_at": feature.latest_available_at.astimezone(UTC),
        "latest_observed_available_at": feature.latest_observed_available_at.astimezone(
            UTC
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
        "reason_codes": json.dumps(reasons, ensure_ascii=False, separators=(",", ":")),
        "source_reason_codes": json.dumps(
            provenance.source_reason_codes,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        **values,
    }


__all__ = [
    "SourceProvenance",
    "archive_id",
    "canonical_record",
    "group_manifests",
    "output_row",
    "source_reason_codes",
]
