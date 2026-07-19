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


def _manifest(audit: Mapping[str, object]) -> PreparedResearchArtifactManifest:
    expected_audit = {
        "build_status": "COMPLETED_RESEARCH_ONLY",
        "system_status": "RESEARCH_ONLY",
        "usage_scope": "MODEL_RESEARCH_ONLY",
        "horizon": 5,
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
    if set(values) != expected_fields:
        raise PreparedResearchArtifactSourceError(
            "PREPARED_RESEARCH_ARTIFACT_MANIFEST_INVALID",
            "Prepared research artifact manifest fields do not match the contract",
        )
    integer_fields = {"byte_size", "row_count", "horizon"}
    if any(
        not isinstance(values[name], int) or isinstance(values[name], bool)
        for name in integer_fields
    ) or any(
        not isinstance(values[name], str)
        for name in expected_fields.difference(integer_fields)
    ):
        raise PreparedResearchArtifactSourceError(
            "PREPARED_RESEARCH_ARTIFACT_MANIFEST_INVALID",
            "Prepared research artifact manifest types do not match the contract",
        )
    try:
        return PreparedResearchArtifactManifest(
            **dict(values)  # pyright: ignore[reportArgumentType]
        )
    except (TypeError, ValueError) as error:
        raise PreparedResearchArtifactSourceError(
            "PREPARED_RESEARCH_ARTIFACT_MANIFEST_INVALID",
            "Prepared research artifact manifest fails its frozen contract",
        ) from error


@final
class PreparedResearchArtifactRepository:
    """Load only a Parquet artifact verified against its typed audit sidecar."""

    def __init__(self, parquet_path: str | Path, audit_path: str | Path) -> None:
        self.parquet_path = Path(parquet_path)
        self.audit_path = Path(audit_path)

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
        manifest = _manifest(audit)
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
        )


__all__ = [
    "PreparedResearchArtifactRepository",
    "PreparedResearchArtifactSourceError",
]
