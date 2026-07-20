"""Opaque read-back proof and sidecar parser for TPEX feature deltas."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .tpex_daily_feature_delta_contracts import (
    TpexDailyFeatureDeltaError,
    TpexDailyFeatureDeltaManifest,
)


_VERIFIED_DELTA_PROOF = object()


@dataclass(frozen=True, init=False)
class VerifiedTpexDailyFeatureDelta:
    path: Path
    manifest: TpexDailyFeatureDeltaManifest
    _proof: object

    def __init__(
        self,
        *,
        path: Path,
        manifest: TpexDailyFeatureDeltaManifest,
        _proof: object,
    ) -> None:
        if _proof is not _VERIFIED_DELTA_PROOF:
            raise TypeError("verified TPEX feature delta requires read-back proof")
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "manifest", manifest)
        object.__setattr__(self, "_proof", _proof)


def verified_tpex_daily_feature_delta(
    path: Path,
    manifest: TpexDailyFeatureDeltaManifest,
) -> VerifiedTpexDailyFeatureDelta:
    return VerifiedTpexDailyFeatureDelta(
        path=path,
        manifest=manifest,
        _proof=_VERIFIED_DELTA_PROOF,
    )


def daily_delta_manifest_from_object(
    value: object,
) -> TpexDailyFeatureDeltaManifest:
    if isinstance(value, TpexDailyFeatureDeltaManifest):
        return value
    if not isinstance(value, Mapping):
        raise TpexDailyFeatureDeltaError(
            "TPEX_DAILY_FEATURE_DELTA_MANIFEST_INVALID",
            "A typed TPEX feature delta manifest is required",
        )
    return TpexDailyFeatureDeltaManifest.from_mapping(cast(Mapping[str, object], value))


__all__ = [
    "VerifiedTpexDailyFeatureDelta",
    "daily_delta_manifest_from_object",
    "verified_tpex_daily_feature_delta",
]
