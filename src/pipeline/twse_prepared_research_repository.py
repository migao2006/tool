"""Verified repository for a prepared TWSE research artifact and sidecar."""

# pyright: reportAny=false, reportExplicitAny=false
# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from datetime import date
import json
from pathlib import Path
from typing import cast, final

from .contracts import PipelineBatch, PipelineMode
from .repositories import DataSourceError
from .twse_prepared_research_artifact import PreparedResearchArtifactWriter
from .twse_prepared_research_contracts import (
    FeatureArtifactSourceProvenance,
    PreparedResearchArtifactError,
    PreparedResearchArtifactManifest,
)


class PreparedResearchArtifactSourceError(DataSourceError):
    """Stable failure raised before an unverified artifact reaches a model."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code: str = reason_code


def _read_audit(path: Path) -> Mapping[str, object]:
    if not path.is_file() or path.stat().st_size == 0:
        raise PreparedResearchArtifactSourceError(
            "PREPARED_RESEARCH_ARTIFACT_AUDIT_UNAVAILABLE",
            "Prepared research artifact audit is unavailable",
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PreparedResearchArtifactSourceError(
            "PREPARED_RESEARCH_ARTIFACT_AUDIT_INVALID",
            "Prepared research artifact audit is not valid JSON",
        ) from error
    if not isinstance(value, Mapping):
        raise PreparedResearchArtifactSourceError(
            "PREPARED_RESEARCH_ARTIFACT_AUDIT_INVALID",
            "Prepared research artifact audit must be an object",
        )
    return cast(Mapping[str, object], value)


def _manifest(
    audit: Mapping[str, object],
    *,
    expected_market: str,
) -> PreparedResearchArtifactManifest:
    expected_audit = {
        "build_status": "COMPLETED_RESEARCH_ONLY",
        "system_status": "RESEARCH_ONLY",
        "usage_scope": "MODEL_RESEARCH_ONLY",
        "horizon": 5,
        "market": expected_market,
        "prepared_artifact_read_back_verified": True,
    }
    if any(audit.get(name) != expected for name, expected in expected_audit.items()):
        raise PreparedResearchArtifactSourceError(
            "PREPARED_RESEARCH_ARTIFACT_AUDIT_INVALID",
            "Prepared research artifact audit does not authorize research training",
        )
    raw = audit.get("prepared_artifact_manifest")
    if not isinstance(raw, Mapping):
        raise PreparedResearchArtifactSourceError(
            "PREPARED_RESEARCH_ARTIFACT_MANIFEST_INVALID",
            "Prepared research artifact audit has no typed manifest",
        )
    values = cast(Mapping[str, object], raw)
    expected_fields = {field.name for field in fields(PreparedResearchArtifactManifest)}
    optional_fields = {
        "feature_source_run_id",
        "feature_source_run_sha",
        "feature_source_artifact_id",
        "feature_source_artifact_digest",
    }
    required_fields = expected_fields.difference(optional_fields)
    if not required_fields.issubset(values) or not set(values).issubset(
        expected_fields
    ):
        raise PreparedResearchArtifactSourceError(
            "PREPARED_RESEARCH_ARTIFACT_MANIFEST_INVALID",
            "Prepared research artifact manifest fields do not match the contract",
        )
    integer_fields = {"byte_size", "row_count", "horizon"}
    if (
        any(
            not isinstance(values[name], int) or isinstance(values[name], bool)
            for name in integer_fields
        )
        or any(
            not isinstance(values[name], str)
            for name in required_fields.difference(integer_fields)
        )
        or any(
            name in values
            and values[name] is not None
            and not isinstance(values[name], str)
            for name in optional_fields
        )
    ):
        raise PreparedResearchArtifactSourceError(
            "PREPARED_RESEARCH_ARTIFACT_MANIFEST_INVALID",
            "Prepared research artifact manifest types do not match the contract",
        )
    try:
        normalized = dict(values)
        for name in optional_fields:
            _ = normalized.setdefault(name, None)
        manifest = PreparedResearchArtifactManifest(
            **normalized  # pyright: ignore[reportArgumentType]
        )
    except (TypeError, ValueError) as error:
        raise PreparedResearchArtifactSourceError(
            "PREPARED_RESEARCH_ARTIFACT_MANIFEST_INVALID",
            "Prepared research artifact manifest fails its frozen contract",
        ) from error
    raw_feature_source = audit.get("feature_source_provenance")
    if manifest.feature_source_run_id is not None:
        expected_feature_source = FeatureArtifactSourceProvenance(
            run_id=manifest.feature_source_run_id,
            run_sha=manifest.feature_source_run_sha or "",
            artifact_id=manifest.feature_source_artifact_id or "",
            artifact_digest=manifest.feature_source_artifact_digest,
        ).to_dict()
        if (
            not isinstance(raw_feature_source, Mapping)
            or dict(raw_feature_source) != expected_feature_source
        ):
            raise PreparedResearchArtifactSourceError(
                "PREPARED_RESEARCH_ARTIFACT_AUDIT_INVALID",
                "Prepared feature source provenance does not match its manifest",
            )
    elif raw_feature_source is not None:
        raise PreparedResearchArtifactSourceError(
            "PREPARED_RESEARCH_ARTIFACT_AUDIT_INVALID",
            "Prepared feature source provenance has no manifest identity",
        )
    return manifest


@final
class PreparedResearchArtifactRepository:
    """Load only a Parquet artifact verified against its typed audit sidecar."""

    def __init__(
        self,
        parquet_path: str | Path,
        audit_path: str | Path,
        *,
        expected_market: str = "TWSE",
    ) -> None:
        normalized_market = expected_market.strip().upper()
        if normalized_market not in {"TWSE", "TPEX"}:
            raise ValueError("prepared artifact market is unsupported")
        self.parquet_path = Path(parquet_path)
        self.audit_path = Path(audit_path)
        self.expected_market: str = normalized_market

    def load(
        self,
        *,
        mode: PipelineMode,
        horizon: int,
        as_of_date: date | None,
    ) -> PipelineBatch:
        if mode is not PipelineMode.TRAIN or as_of_date is not None:
            raise PreparedResearchArtifactSourceError(
                "PREPARED_RESEARCH_ARTIFACT_MODE_UNSUPPORTED",
                "Prepared research artifact currently supports training only",
            )
        if horizon != 5:
            raise PreparedResearchArtifactSourceError(
                "UNSUPPORTED_HORIZON",
                "Prepared research artifact is bound to horizon=5",
            )
        if not self.parquet_path.is_file() or self.parquet_path.stat().st_size == 0:
            raise PreparedResearchArtifactSourceError(
                "PREPARED_RESEARCH_ARTIFACT_UNAVAILABLE",
                "Prepared research artifact is unavailable",
            )

        audit = _read_audit(self.audit_path)
        manifest = _manifest(audit, expected_market=self.expected_market)
        if audit.get("output_file") != self.parquet_path.name:
            raise PreparedResearchArtifactSourceError(
                "PREPARED_RESEARCH_ARTIFACT_AUDIT_INVALID",
                "Prepared research artifact filename does not match its audit",
            )
        try:
            dataset = PreparedResearchArtifactWriter().verify(
                self.parquet_path,
                manifest,
            )
        except PreparedResearchArtifactError as error:
            raise PreparedResearchArtifactSourceError(
                error.reason_code,
                "Prepared research artifact failed read-back verification",
            ) from error
        return PipelineBatch(
            records=dataset.frame,
            source_uri=self.parquet_path.resolve().as_uri(),
            source_hash=manifest.parquet_sha256,
            source_metadata={"prepared_artifact_manifest": manifest.to_dict()},
        )


__all__ = [
    "PreparedResearchArtifactRepository",
    "PreparedResearchArtifactSourceError",
]
