"""TPEX aliases and frozen metadata for the shared archive feature pipeline."""

from __future__ import annotations

from types import MappingProxyType

from .archive_feature_market import archive_feature_market_profile
from .archive_feature_contracts import (
    ArchiveFeatureAudit as TpexArchiveFeatureAudit,
    ArchiveFeatureBuildError as TpexArchiveFeatureBuildError,
    CurrentSecurityIdentity as TpexCurrentSecurityIdentity,
    IdentitySnapshot as TpexIdentitySnapshot,
    dataset_snapshot_hash as _dataset_snapshot_hash,
    identity_snapshot_hash,
)


_PROFILE = archive_feature_market_profile("TPEX")
TPEX_ARCHIVE_SCOPE_FILTERS = MappingProxyType(dict(_PROFILE.scope_filters))
TPEX_DECISION_TIME_POLICY_VERSION = _PROFILE.decision_time_policy_version
TPEX_ARCHIVE_FEATURE_DATASET_VERSION = _PROFILE.dataset_version
TPEX_ARCHIVE_FEATURE_GLOBAL_REASONS = _PROFILE.global_reason_codes


def dataset_snapshot_hash(
    *,
    source_archive_snapshot_sha256: str,
    current_identity_snapshot_sha256: str,
) -> str:
    return _dataset_snapshot_hash(
        source_archive_snapshot_sha256=source_archive_snapshot_sha256,
        current_identity_snapshot_sha256=current_identity_snapshot_sha256,
        market="TPEX",
    )


__all__ = [
    "TPEX_ARCHIVE_FEATURE_DATASET_VERSION",
    "TPEX_ARCHIVE_FEATURE_GLOBAL_REASONS",
    "TPEX_ARCHIVE_SCOPE_FILTERS",
    "TPEX_DECISION_TIME_POLICY_VERSION",
    "TpexArchiveFeatureAudit",
    "TpexArchiveFeatureBuildError",
    "TpexCurrentSecurityIdentity",
    "TpexIdentitySnapshot",
    "dataset_snapshot_hash",
    "identity_snapshot_hash",
]
