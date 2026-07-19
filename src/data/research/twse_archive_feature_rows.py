"""Row adaptation between verified archives, features, and Parquet output."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
import json
from typing import cast
from zoneinfo import ZoneInfo

from src.data.archive.contracts import HistoricalArchiveManifest
from src.features.twse_price_volume_contracts import TwsePriceVolumeFeatureRow

from .twse_archive_feature_contracts import (
    TWSE_ARCHIVE_FEATURE_GLOBAL_REASONS,
    TWSE_DECISION_TIME_POLICY_VERSION,
    TwseArchiveFeatureBuildError,
    TwseCurrentSecurityIdentity,
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
        raise TwseArchiveFeatureBuildError(
            "ARCHIVE_ID_INVALID",
            "Archive manifest contains an invalid archive_id",
        )
    return value


def group_manifests(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, list[Mapping[str, object]]]:
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        manifest = HistoricalArchiveManifest.from_mapping(row)
        grouped.setdefault(manifest.source_symbol, []).append(row)
    return dict(sorted(grouped.items()))


def source_reason_codes(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise TwseArchiveFeatureBuildError(
            "ARCHIVE_REASON_CODES_INVALID",
            "Archive reason_codes must be canonical JSON",
        )
    try:
        parsed = cast(object, json.loads(value))
    except json.JSONDecodeError as error:
        raise TwseArchiveFeatureBuildError(
            "ARCHIVE_REASON_CODES_INVALID",
            "Archive reason_codes are not valid JSON",
        ) from error
    if not isinstance(parsed, list):
        raise TwseArchiveFeatureBuildError(
            "ARCHIVE_REASON_CODES_INVALID",
            "Archive reason_codes are not a string array",
        )
    raw_reasons = cast(list[object], parsed)
    if any(not isinstance(reason, str) or not reason for reason in raw_reasons):
        raise TwseArchiveFeatureBuildError(
            "ARCHIVE_REASON_CODES_INVALID",
            "Archive reason_codes are not a string array",
        )
    return tuple(dict.fromkeys(cast(list[str], raw_reasons)))


def canonical_record(
    row: Mapping[str, object],
    *,
    identity: TwseCurrentSecurityIdentity,
) -> dict[str, object]:
    trade_date = row.get("trade_date")
    if type(trade_date) is not date:
        raise TwseArchiveFeatureBuildError(
            "PARSED_ARCHIVE_TRADE_DATE_INVALID",
            "Parsed archive row is missing its trade date",
        )
    return {
        "security_id": identity.security_id,
        "listing_period_id": identity.listing_period_id,
        "market": "TWSE",
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
    feature: TwsePriceVolumeFeatureRow,
    *,
    identity: TwseCurrentSecurityIdentity,
    provenance: SourceProvenance,
    dataset_snapshot_sha256: str,
    source_archive_snapshot_sha256: str,
    current_identity_snapshot_sha256: str,
) -> dict[str, object]:
    if (
        feature.latest_available_at is None
        or feature.latest_observed_available_at is None
        or identity.listing_date is None
    ):
        raise TwseArchiveFeatureBuildError(
            "ELIGIBLE_FEATURE_PROVENANCE_MISSING",
            "Eligible feature row is missing required provenance",
        )
    values = dict(feature.feature_values)
    if any(value is None for value in values.values()):
        raise TwseArchiveFeatureBuildError(
            "ELIGIBLE_FEATURE_VALUE_MISSING",
            "Hard-fail feature rows cannot be written",
        )
    reasons = tuple(
        dict.fromkeys(
            (
                *TWSE_ARCHIVE_FEATURE_GLOBAL_REASONS,
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
        "market": "TWSE",
        "asset_type": "COMMON_STOCK",
        "listing_date": identity.listing_date,
        "decision_date": feature.decision_date,
        "decision_at": feature.decision_at,
        "horizon": feature.horizon,
        "decision_time_policy_version": TWSE_DECISION_TIME_POLICY_VERSION,
        "feature_schema_version": feature.feature_schema_version,
        "feature_schema_hash": feature.feature_schema_hash,
        "price_basis": feature.price_basis,
        "availability_mode": feature.availability_mode,
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
