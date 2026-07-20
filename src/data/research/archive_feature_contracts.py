"""Market-neutral contracts for archive-to-feature research pipelines."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from .archive_feature_market import archive_feature_market_profile


_DEFAULT_PROFILE = archive_feature_market_profile("TWSE")


class ArchiveFeatureBuildError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code: str = reason_code


def _aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class CurrentSecurityIdentity:
    """Current venue identity, never presented as historical identity."""

    security_id: int
    symbol: str
    listing_date: date | None
    delisting_date: date | None = None
    market: str = "TWSE"
    asset_type: str = "COMMON_STOCK"

    def __post_init__(self) -> None:
        if self.security_id <= 0 or not self.symbol.strip():
            raise ValueError("current security identity is invalid")
        if self.market not in {"TWSE", "TPEX"} or self.asset_type != "COMMON_STOCK":
            raise ValueError("identity is outside the common-stock venue scope")
        if (
            self.delisting_date is not None
            and self.listing_date is not None
            and self.delisting_date < self.listing_date
        ):
            raise ValueError("delisting_date precedes listing_date")

    @property
    def listing_period_id(self) -> str:
        end = self.delisting_date.isoformat() if self.delisting_date else "OPEN"
        start = self.listing_date.isoformat() if self.listing_date else "UNKNOWN"
        return f"CURRENT:{self.market}:{self.symbol}:{start}:{end}"


@dataclass(frozen=True)
class IdentitySnapshot:
    by_symbol: Mapping[str, CurrentSecurityIdentity]
    snapshot_sha256: str

    def __post_init__(self) -> None:
        if any(
            symbol != identity.symbol for symbol, identity in self.by_symbol.items()
        ):
            raise ValueError("identity snapshot keys do not match symbols")
        if len(self.snapshot_sha256) != 64:
            raise ValueError("identity snapshot hash is invalid")


def identity_snapshot_hash(
    identities: Mapping[str, CurrentSecurityIdentity],
) -> str:
    payload = [
        {
            "asset_type": identity.asset_type,
            "delisting_date": (
                identity.delisting_date.isoformat()
                if identity.delisting_date is not None
                else None
            ),
            "listing_date": (
                identity.listing_date.isoformat()
                if identity.listing_date is not None
                else None
            ),
            "market": identity.market,
            "security_id": identity.security_id,
            "symbol": identity.symbol,
        }
        for identity in sorted(identities.values(), key=lambda value: value.symbol)
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def dataset_snapshot_hash(
    *,
    source_archive_snapshot_sha256: str,
    current_identity_snapshot_sha256: str,
    market: str = "TWSE",
) -> str:
    profile = archive_feature_market_profile(market)
    payload = {
        "availability_mode": "RESEARCH_SCHEDULING_HINT",
        "current_identity_snapshot_sha256": current_identity_snapshot_sha256,
        "dataset_version": profile.dataset_version,
        "decision_time_policy_version": profile.decision_time_policy_version,
        "feature_schema_hash": profile.feature.schema_hash,
        "horizon": 5,
        "scope_filters": dict(profile.scope_filters),
        "source_archive_snapshot_sha256": source_archive_snapshot_sha256,
        "system_status": "RESEARCH_ONLY",
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ArchiveFeatureAudit:
    generated_at: datetime
    dataset_snapshot_sha256: str
    source_archive_snapshot_sha256: str
    current_identity_snapshot_sha256: str
    manifest_count: int
    manifest_symbol_count: int
    current_identity_count: int
    verified_archive_count: int
    source_row_count: int
    parsed_source_row_count: int
    output_row_count: int
    excluded_row_count: int
    exclusion_reason_counts: Mapping[str, int]
    market: str = "TWSE"
    dataset_version: str = _DEFAULT_PROFILE.dataset_version
    feature_schema_version: str = _DEFAULT_PROFILE.feature.schema_version
    feature_schema_hash: str = _DEFAULT_PROFILE.feature.schema_hash
    decision_time_policy_version: str = _DEFAULT_PROFILE.decision_time_policy_version
    availability_mode: str = "RESEARCH_SCHEDULING_HINT"
    horizon: int = 5
    label_status: str = "LABELS_NOT_ASSEMBLED"
    usage_scope: str = "FEATURE_RESEARCH_ONLY"
    system_status: str = "RESEARCH_ONLY"
    reason_codes: tuple[str, ...] = _DEFAULT_PROFILE.global_reason_codes

    def __post_init__(self) -> None:
        profile = archive_feature_market_profile(self.market)
        _aware(self.generated_at, "generated_at")
        for digest in (
            self.dataset_snapshot_sha256,
            self.source_archive_snapshot_sha256,
            self.current_identity_snapshot_sha256,
            self.feature_schema_hash,
        ):
            if len(digest) != 64:
                raise ValueError("audit contains an invalid SHA-256 digest")
        counts = (
            self.manifest_count,
            self.manifest_symbol_count,
            self.current_identity_count,
            self.verified_archive_count,
            self.source_row_count,
            self.parsed_source_row_count,
            self.output_row_count,
            self.excluded_row_count,
        )
        if any(count < 0 for count in counts):
            raise ValueError("audit counts cannot be negative")
        if self.verified_archive_count != self.manifest_count:
            raise ValueError(
                "every manifest must be verified before output is complete"
            )
        if self.system_status != "RESEARCH_ONLY" or self.horizon != 5:
            raise ValueError("archive features cannot be promoted or relabeled")
        if self.label_status != "LABELS_NOT_ASSEMBLED":
            raise ValueError("this pipeline cannot assemble labels")
        if (
            self.dataset_version != profile.dataset_version
            or self.feature_schema_version != profile.feature.schema_version
            or self.feature_schema_hash != profile.feature.schema_hash
            or self.decision_time_policy_version
            != profile.decision_time_policy_version
            or self.reason_codes != profile.global_reason_codes
        ):
            raise ValueError("audit metadata does not match its market profile")

    def as_json(self) -> dict[str, object]:
        profile = archive_feature_market_profile(self.market)
        return {
            "generated_at": self.generated_at.isoformat(),
            "dataset_version": self.dataset_version,
            "dataset_snapshot_sha256": self.dataset_snapshot_sha256,
            "source_archive_snapshot_sha256": self.source_archive_snapshot_sha256,
            "current_identity_snapshot_sha256": self.current_identity_snapshot_sha256,
            "market": self.market,
            "scope_filters": dict(profile.scope_filters),
            "manifest_count": self.manifest_count,
            "manifest_symbol_count": self.manifest_symbol_count,
            "current_identity_count": self.current_identity_count,
            "verified_archive_count": self.verified_archive_count,
            "source_row_count": self.source_row_count,
            "parsed_source_row_count": self.parsed_source_row_count,
            "output_row_count": self.output_row_count,
            "excluded_row_count": self.excluded_row_count,
            "exclusion_reason_counts": dict(self.exclusion_reason_counts),
            "feature_schema_version": self.feature_schema_version,
            "feature_schema_hash": self.feature_schema_hash,
            "decision_time_policy_version": self.decision_time_policy_version,
            "availability_mode": self.availability_mode,
            "horizon": self.horizon,
            "label_status": self.label_status,
            "usage_scope": self.usage_scope,
            "system_status": self.system_status,
            "reason_codes": list(self.reason_codes),
        }


__all__ = [
    "ArchiveFeatureAudit",
    "ArchiveFeatureBuildError",
    "CurrentSecurityIdentity",
    "IdentitySnapshot",
    "dataset_snapshot_hash",
    "identity_snapshot_hash",
]
