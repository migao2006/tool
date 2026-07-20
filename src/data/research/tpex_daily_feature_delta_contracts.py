"""Frozen contracts for one TPEX post-close feature delta."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import re
from typing import ClassVar, Self, cast

from src.features.tpex_price_volume_schema import (
    TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
    TPEX_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
)

from .archive_feature_market import archive_feature_market_profile


TPEX_DAILY_FEATURE_DELTA_VERSION = "tpex-daily-feature-delta-5d-v1"
TPEX_DAILY_FEATURE_DELTA_MANIFEST_VERSION = "tpex-daily-feature-delta-manifest.v1"
TPEX_DAILY_FEATURE_DELTA_REASONS = (
    "CURRENT_SECURITIES_SURVIVORSHIP_MAPPING",
    "HISTORICAL_IDENTITY_NOT_POINT_IN_TIME",
    "TRADING_SESSIONS_DERIVED_PER_SYMBOL",
    "RESEARCH_SCHEDULING_HINT",
    "SUPABASE_DAILY_BAR_DELTA_RESEARCH_ONLY",
    "CANONICAL_DAILY_BAR_ROWS_NOT_RAW_PAYLOAD_VERIFIED",
    "LABELS_NOT_ASSEMBLED",
    "BENCHMARK_ARCHIVE_NOT_CONNECTED",
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class TpexDailyFeatureDeltaError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code: str = reason_code


def daily_feature_delta_snapshot_hash(
    *,
    source_archive_snapshot_sha256: str,
    current_identity_snapshot_sha256: str,
    daily_bar_snapshot_sha256: str,
    as_of_date: date,
) -> str:
    payload = {
        "as_of_date": as_of_date.isoformat(),
        "current_identity_snapshot_sha256": current_identity_snapshot_sha256,
        "daily_bar_snapshot_sha256": daily_bar_snapshot_sha256,
        "dataset_version": TPEX_DAILY_FEATURE_DELTA_VERSION,
        "feature_schema_hash": TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
        "market": "TPEX",
        "source_archive_snapshot_sha256": source_archive_snapshot_sha256,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _required_text(values: Mapping[str, object], name: str) -> str:
    value = values.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"feature delta manifest is missing {name}")
    return value.strip()


def _positive_integer(values: Mapping[str, object], name: str) -> int:
    value = values.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"feature delta manifest contains invalid {name}")
    return value


def _date(values: Mapping[str, object], name: str) -> date:
    value = values.get(name)
    if type(value) is date:
        return cast(date, value)
    return date.fromisoformat(str(value))


@dataclass(frozen=True)
class TpexDailyFeatureDeltaManifest:
    MARKET: ClassVar[str] = "TPEX"

    parquet_sha256: str
    parquet_schema_sha256: str
    byte_size: int
    row_count: int
    dataset_snapshot_sha256: str
    source_archive_snapshot_sha256: str
    current_identity_snapshot_sha256: str
    daily_bar_snapshot_sha256: str
    as_of_date: date
    dataset_version: str = TPEX_DAILY_FEATURE_DELTA_VERSION
    feature_schema_version: str = TPEX_PRICE_VOLUME_FEATURE_SCHEMA_VERSION
    feature_schema_hash: str = TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH
    decision_time_policy_version: str = archive_feature_market_profile(
        "TPEX"
    ).decision_time_policy_version
    availability_mode: str = "RESEARCH_SCHEDULING_HINT"
    horizon: int = 5
    label_status: str = "LABELS_NOT_ASSEMBLED"
    usage_scope: str = "FEATURE_RESEARCH_ONLY"
    system_status: str = "RESEARCH_ONLY"
    point_in_time_status: str = "UNVERIFIED"
    manifest_version: str = TPEX_DAILY_FEATURE_DELTA_MANIFEST_VERSION

    def __post_init__(self) -> None:
        digests = (
            self.parquet_sha256,
            self.parquet_schema_sha256,
            self.dataset_snapshot_sha256,
            self.source_archive_snapshot_sha256,
            self.current_identity_snapshot_sha256,
            self.daily_bar_snapshot_sha256,
            self.feature_schema_hash,
        )
        if any(_SHA256.fullmatch(value) is None for value in digests):
            raise ValueError("feature delta manifest contains an invalid SHA-256")
        if self.byte_size <= 0 or self.row_count <= 0:
            raise ValueError("feature delta artifact must contain rows and bytes")
        expected = (
            self.manifest_version == TPEX_DAILY_FEATURE_DELTA_MANIFEST_VERSION
            and self.dataset_version == TPEX_DAILY_FEATURE_DELTA_VERSION
            and self.feature_schema_version == TPEX_PRICE_VOLUME_FEATURE_SCHEMA_VERSION
            and self.feature_schema_hash == TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH
            and self.decision_time_policy_version
            == archive_feature_market_profile("TPEX").decision_time_policy_version
            and self.availability_mode == "RESEARCH_SCHEDULING_HINT"
            and self.horizon == 5
            and self.label_status == "LABELS_NOT_ASSEMBLED"
            and self.usage_scope == "FEATURE_RESEARCH_ONLY"
            and self.system_status == "RESEARCH_ONLY"
            and self.point_in_time_status == "UNVERIFIED"
        )
        if not expected:
            raise ValueError("feature delta exceeds the frozen research-only scope")
        snapshot = daily_feature_delta_snapshot_hash(
            source_archive_snapshot_sha256=self.source_archive_snapshot_sha256,
            current_identity_snapshot_sha256=self.current_identity_snapshot_sha256,
            daily_bar_snapshot_sha256=self.daily_bar_snapshot_sha256,
            as_of_date=self.as_of_date,
        )
        if snapshot != self.dataset_snapshot_sha256:
            raise ValueError("feature delta input snapshots do not reproduce its ID")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["as_of_date"] = self.as_of_date.isoformat()
        return payload

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> Self:
        try:
            return cls(
                manifest_version=_required_text(values, "manifest_version"),
                parquet_sha256=_required_text(values, "parquet_sha256").lower(),
                parquet_schema_sha256=_required_text(
                    values, "parquet_schema_sha256"
                ).lower(),
                byte_size=_positive_integer(values, "byte_size"),
                row_count=_positive_integer(values, "row_count"),
                dataset_version=_required_text(values, "dataset_version"),
                dataset_snapshot_sha256=_required_text(
                    values, "dataset_snapshot_sha256"
                ).lower(),
                source_archive_snapshot_sha256=_required_text(
                    values, "source_archive_snapshot_sha256"
                ).lower(),
                current_identity_snapshot_sha256=_required_text(
                    values, "current_identity_snapshot_sha256"
                ).lower(),
                daily_bar_snapshot_sha256=_required_text(
                    values, "daily_bar_snapshot_sha256"
                ).lower(),
                as_of_date=_date(values, "as_of_date"),
                feature_schema_version=_required_text(values, "feature_schema_version"),
                feature_schema_hash=_required_text(
                    values, "feature_schema_hash"
                ).lower(),
                decision_time_policy_version=_required_text(
                    values, "decision_time_policy_version"
                ),
                availability_mode=_required_text(values, "availability_mode"),
                horizon=_positive_integer(values, "horizon"),
                label_status=_required_text(values, "label_status"),
                usage_scope=_required_text(values, "usage_scope"),
                system_status=_required_text(values, "system_status"),
                point_in_time_status=_required_text(values, "point_in_time_status"),
            )
        except (TypeError, ValueError) as error:
            raise TpexDailyFeatureDeltaError(
                "TPEX_DAILY_FEATURE_DELTA_MANIFEST_INVALID",
                "TPEX feature delta manifest is incomplete or inconsistent",
            ) from error


@dataclass(frozen=True)
class TpexDailyFeatureDeltaAudit:
    generated_at: datetime
    as_of_date: date
    dataset_snapshot_sha256: str
    source_archive_snapshot_sha256: str
    current_identity_snapshot_sha256: str
    daily_bar_snapshot_sha256: str
    manifest_count: int
    daily_source_row_count: int
    verified_archive_count: int
    output_row_count: int
    excluded_row_count: int
    exclusion_reason_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        if (
            min(
                self.manifest_count,
                self.daily_source_row_count,
                self.verified_archive_count,
                self.output_row_count,
            )
            <= 0
            or self.excluded_row_count < 0
        ):
            raise ValueError("feature delta audit counts are invalid")
        if self.verified_archive_count != self.manifest_count:
            raise ValueError("every archive must be verified before delta output")
        _ = TpexDailyFeatureDeltaManifest(
            parquet_sha256="0" * 64,
            parquet_schema_sha256="1" * 64,
            byte_size=1,
            row_count=self.output_row_count,
            dataset_snapshot_sha256=self.dataset_snapshot_sha256,
            source_archive_snapshot_sha256=self.source_archive_snapshot_sha256,
            current_identity_snapshot_sha256=self.current_identity_snapshot_sha256,
            daily_bar_snapshot_sha256=self.daily_bar_snapshot_sha256,
            as_of_date=self.as_of_date,
        )

    def as_json(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at.astimezone(timezone.utc).isoformat(),
            "as_of_date": self.as_of_date.isoformat(),
            "market": "TPEX",
            "horizon": 5,
            "dataset_version": TPEX_DAILY_FEATURE_DELTA_VERSION,
            "dataset_snapshot_sha256": self.dataset_snapshot_sha256,
            "source_archive_snapshot_sha256": self.source_archive_snapshot_sha256,
            "current_identity_snapshot_sha256": self.current_identity_snapshot_sha256,
            "daily_bar_snapshot_sha256": self.daily_bar_snapshot_sha256,
            "manifest_count": self.manifest_count,
            "daily_source_row_count": self.daily_source_row_count,
            "verified_archive_count": self.verified_archive_count,
            "output_row_count": self.output_row_count,
            "excluded_row_count": self.excluded_row_count,
            "exclusion_reason_counts": dict(self.exclusion_reason_counts),
            "feature_schema_version": TPEX_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
            "feature_schema_hash": TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
            "availability_mode": "RESEARCH_SCHEDULING_HINT",
            "label_status": "LABELS_NOT_ASSEMBLED",
            "usage_scope": "FEATURE_RESEARCH_ONLY",
            "system_status": "RESEARCH_ONLY",
            "point_in_time_status": "UNVERIFIED",
            "reason_codes": list(TPEX_DAILY_FEATURE_DELTA_REASONS),
        }


__all__ = [
    "TPEX_DAILY_FEATURE_DELTA_MANIFEST_VERSION",
    "TPEX_DAILY_FEATURE_DELTA_REASONS",
    "TPEX_DAILY_FEATURE_DELTA_VERSION",
    "TpexDailyFeatureDeltaAudit",
    "TpexDailyFeatureDeltaError",
    "TpexDailyFeatureDeltaManifest",
    "daily_feature_delta_snapshot_hash",
]
