"""Backward-compatible TWSE contracts for the shared archive feature pipeline."""

from types import MappingProxyType

from .archive_feature_contracts import (
    ArchiveFeatureAudit as TwseArchiveFeatureAudit,
    ArchiveFeatureBuildError as TwseArchiveFeatureBuildError,
    CurrentSecurityIdentity as TwseCurrentSecurityIdentity,
    IdentitySnapshot as TwseIdentitySnapshot,
    dataset_snapshot_hash as _dataset_snapshot_hash,
    identity_snapshot_hash,
)
from .archive_feature_market import archive_feature_market_profile

_PROFILE = archive_feature_market_profile("TWSE")
TWSE_ARCHIVE_SCOPE_FILTERS = MappingProxyType(dict(_PROFILE.scope_filters))
TWSE_DECISION_TIME_POLICY_VERSION = _PROFILE.decision_time_policy_version
TWSE_ARCHIVE_FEATURE_DATASET_VERSION = _PROFILE.dataset_version
TWSE_ARCHIVE_FEATURE_GLOBAL_REASONS = _PROFILE.global_reason_codes


def dataset_snapshot_hash(
    *,
    source_archive_snapshot_sha256: str,
    current_identity_snapshot_sha256: str,
) -> str:
    return _dataset_snapshot_hash(
        source_archive_snapshot_sha256=source_archive_snapshot_sha256,
        current_identity_snapshot_sha256=current_identity_snapshot_sha256,
        market="TWSE",
    )


__all__ = [
    "TWSE_ARCHIVE_FEATURE_DATASET_VERSION",
    "TWSE_ARCHIVE_FEATURE_GLOBAL_REASONS",
    "TWSE_ARCHIVE_SCOPE_FILTERS",
    "TWSE_DECISION_TIME_POLICY_VERSION",
    "TwseArchiveFeatureAudit",
    "TwseArchiveFeatureBuildError",
    "TwseCurrentSecurityIdentity",
    "TwseIdentitySnapshot",
    "dataset_snapshot_hash",
    "identity_snapshot_hash",
]
