"""Read one verified, unlabeled TWSE feature cross-section for inference."""

from __future__ import annotations

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false
# pyright: reportOperatorIssue=false

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any, ClassVar, cast, final

from src.data.research.twse_feature_artifact_contracts import (
    TwseFeatureArtifactManifest,
    TwseFeatureArtifactReadError,
    manifest_from_object,
)
from src.data.research.twse_feature_artifact_reader import TwseFeatureArtifactReader
from src.features.twse_price_volume_schema import TWSE_PRICE_VOLUME_FEATURE_NAMES


@dataclass(frozen=True)
class LatestTwseFeatureCrossSection:
    frame: Any
    as_of_date: date
    manifest: TwseFeatureArtifactManifest


class LatestTwseFeatureSourceError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code: str = reason_code


def _audit(path: Path) -> dict[str, object]:
    try:
        value = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LatestTwseFeatureSourceError(
            "TWSE_FEATURE_ARTIFACT_AUDIT_INVALID",
            "The TWSE feature audit cannot be read",
        ) from error
    if not isinstance(value, dict):
        raise LatestTwseFeatureSourceError(
            "TWSE_FEATURE_ARTIFACT_AUDIT_INVALID",
            "The TWSE feature audit must be a JSON object",
        )
    return cast(dict[str, object], value)


def _pyarrow_modules() -> tuple[Any, Any]:
    try:
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
    except ModuleNotFoundError as error:
        raise LatestTwseFeatureSourceError(
            "PARQUET_DEPENDENCY_MISSING",
            "pyarrow is required for TWSE feature inference",
        ) from error
    return pc, pq


@final
class LatestTwseFeatureRepository:
    """Fail closed unless Parquet bytes and the sidecar agree exactly."""

    _COLUMNS: ClassVar[tuple[str, ...]] = (
        "symbol",
        "market",
        "asset_type",
        "decision_date",
        "decision_at",
        "horizon",
        "feature_schema_hash",
        "latest_available_at",
        "latest_observed_available_at",
        "point_in_time_audit_pass",
        "hard_fail",
        "reason_codes",
        "research_limitation_reason_codes",
        "decision_close_price",
        *TWSE_PRICE_VOLUME_FEATURE_NAMES,
    )

    def load(
        self,
        parquet_path: str | Path,
        audit_path: str | Path,
        *,
        as_of_date: date | None = None,
    ) -> LatestTwseFeatureCrossSection:
        parquet = Path(parquet_path)
        audit = _audit(Path(audit_path))
        if audit.get("output_file") != parquet.name:
            raise LatestTwseFeatureSourceError(
                "TWSE_FEATURE_ARTIFACT_AUDIT_INVALID",
                "Feature filename does not match its audit",
            )
        try:
            manifest = manifest_from_object(audit.get("feature_artifact_manifest"))
            verified = TwseFeatureArtifactReader().verify(parquet, manifest)
        except TwseFeatureArtifactReadError as error:
            raise LatestTwseFeatureSourceError(
                error.reason_code,
                "TWSE feature artifact failed read-back verification",
            ) from error

        pc, pq = _pyarrow_modules()
        dates = pq.read_table(verified.path, columns=["decision_date"])[
            "decision_date"
        ]
        if as_of_date is not None:
            dates = pc.filter(dates, pc.less_equal(dates, as_of_date))
        if len(dates) == 0:
            raise LatestTwseFeatureSourceError(
                "TWSE_FEATURE_AS_OF_DATE_UNAVAILABLE",
                "No verified feature cross-section exists on or before the request",
            )
        latest_value = pc.max(dates).as_py()
        if type(latest_value) is not date:
            raise LatestTwseFeatureSourceError(
                "TWSE_FEATURE_DECISION_DATE_INVALID",
                "Latest TWSE feature date is invalid",
            )
        try:
            table = pq.read_table(
                verified.path,
                columns=list(self._COLUMNS),
                filters=[("decision_date", "=", latest_value)],
            )
        except Exception as error:
            raise LatestTwseFeatureSourceError(
                "TWSE_FEATURE_CROSS_SECTION_READ_FAILED",
                "Latest TWSE feature cross-section cannot be read",
            ) from error
        frame = table.to_pandas()
        self._validate(frame, latest_value, manifest)
        return LatestTwseFeatureCrossSection(
            frame=frame,
            as_of_date=latest_value,
            manifest=manifest,
        )

    @staticmethod
    def _validate(
        frame: Any,
        as_of_date: date,
        manifest: TwseFeatureArtifactManifest,
    ) -> None:
        import pandas as pd

        if frame.empty or frame["symbol"].duplicated().any():
            raise LatestTwseFeatureSourceError(
                "TWSE_FEATURE_CROSS_SECTION_INVALID",
                "Latest feature cross-section must contain unique symbols",
            )
        expected = (
            frame["decision_date"].eq(as_of_date).all()
            and frame["horizon"].eq(5).all()
            and frame["market"].eq("TWSE").all()
            and frame["asset_type"].eq("COMMON_STOCK").all()
            and frame["feature_schema_hash"].eq(manifest.feature_schema_hash).all()
            and not frame["hard_fail"].any()
        )
        if not expected:
            raise LatestTwseFeatureSourceError(
                "TWSE_FEATURE_CROSS_SECTION_INVALID",
                "Latest feature rows exceed the frozen TWSE research scope",
            )
        decision_at = pd.to_datetime(frame["decision_at"], utc=True, errors="coerce")
        available_at = pd.to_datetime(
            frame["latest_available_at"], utc=True, errors="coerce"
        )
        if (
            decision_at.isna().any()
            or available_at.isna().any()
            or (available_at > decision_at).any()
        ):
            raise LatestTwseFeatureSourceError(
                "TWSE_FEATURE_POINT_IN_TIME_VIOLATION",
                "A feature is not available by its research decision time",
            )
        close = pd.to_numeric(frame["decision_close_price"], errors="coerce")
        adv20 = pd.to_numeric(frame["adv20_ntd"], errors="coerce")
        if close.isna().any() or (close <= 0).any() or adv20.isna().any() or (
            adv20 <= 0
        ).any():
            raise LatestTwseFeatureSourceError(
                "TWSE_FEATURE_COST_CONTEXT_INVALID",
                "Current price and ADV20 are required for auditable costs",
            )


__all__ = [
    "LatestTwseFeatureCrossSection",
    "LatestTwseFeatureRepository",
    "LatestTwseFeatureSourceError",
]
