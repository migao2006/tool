"""Read one verified, unlabeled venue feature cross-section for inference."""

from __future__ import annotations

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false
# pyright: reportOperatorIssue=false

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any, ClassVar, Protocol, cast


class LatestFeatureManifest(Protocol):
    MARKET: ClassVar[str]

    @property
    def parquet_sha256(self) -> str: ...

    @property
    def dataset_snapshot_sha256(self) -> str: ...

    @property
    def source_archive_snapshot_sha256(self) -> str: ...

    @property
    def feature_schema_hash(self) -> str: ...

    def to_dict(self) -> dict[str, object]: ...


@dataclass(frozen=True)
class LatestFeatureCrossSection:
    frame: Any
    as_of_date: date
    manifest: LatestFeatureManifest
    market: str


class LatestFeatureSourceError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code: str = reason_code


def _audit(path: Path, market: str) -> dict[str, object]:
    try:
        value = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LatestFeatureSourceError(
            f"{market}_FEATURE_ARTIFACT_AUDIT_INVALID",
            f"The {market} feature audit cannot be read",
        ) from error
    if not isinstance(value, dict):
        raise LatestFeatureSourceError(
            f"{market}_FEATURE_ARTIFACT_AUDIT_INVALID",
            f"The {market} feature audit must be a JSON object",
        )
    return cast(dict[str, object], value)


def _pyarrow_modules() -> tuple[Any, Any]:
    try:
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
    except ModuleNotFoundError as error:
        raise LatestFeatureSourceError(
            "PARQUET_DEPENDENCY_MISSING",
            "pyarrow is required for feature inference",
        ) from error
    return pc, pq


class LatestFeatureRepository:
    """Fail closed unless bytes, sidecar, schema, and venue agree exactly."""

    def __init__(
        self,
        *,
        market: str,
        feature_names: Sequence[str],
        manifest_parser: Callable[[object], LatestFeatureManifest],
        reader: Any,
        manifest_field: str = "feature_artifact_manifest",
        read_back_flag_field: str | None = None,
    ) -> None:
        normalized = market.strip().upper()
        if normalized not in {"TWSE", "TPEX"}:
            raise ValueError("latest feature market is unsupported")
        self.market = normalized
        self.feature_names = tuple(feature_names)
        self.manifest_parser = manifest_parser
        self.reader = reader
        self.manifest_field = manifest_field
        self.read_back_flag_field = read_back_flag_field

    @property
    def columns(self) -> tuple[str, ...]:
        return (
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
            *self.feature_names,
        )

    def load(
        self,
        parquet_path: str | Path,
        audit_path: str | Path,
        *,
        as_of_date: date | None = None,
    ) -> LatestFeatureCrossSection:
        parquet = Path(parquet_path)
        audit = _audit(Path(audit_path), self.market)
        if audit.get("output_file") != parquet.name:
            raise self._error(
                "FEATURE_ARTIFACT_AUDIT_INVALID",
                "Feature filename does not match its audit",
            )
        if (
            self.read_back_flag_field is not None
            and audit.get(self.read_back_flag_field) is not True
        ):
            raise self._error(
                "FEATURE_ARTIFACT_AUDIT_INVALID",
                "Feature read-back verification is not recorded",
            )
        try:
            manifest = self.manifest_parser(audit.get(self.manifest_field))
            verified = self.reader.verify(parquet, manifest)
        except Exception as error:
            reason = getattr(
                error, "reason_code", f"{self.market}_FEATURE_ARTIFACT_INVALID"
            )
            raise LatestFeatureSourceError(
                str(reason),
                f"{self.market} feature artifact failed read-back verification",
            ) from error

        pc, pq = _pyarrow_modules()
        dates = pq.read_table(verified.path, columns=["decision_date"])["decision_date"]
        if as_of_date is not None:
            dates = pc.filter(dates, pc.less_equal(dates, as_of_date))
        if len(dates) == 0:
            raise self._error(
                "FEATURE_AS_OF_DATE_UNAVAILABLE",
                "No verified feature cross-section exists on or before the request",
            )
        latest_value = pc.max(dates).as_py()
        if type(latest_value) is not date:
            raise self._error(
                "FEATURE_DECISION_DATE_INVALID", "Latest feature date is invalid"
            )
        try:
            table = pq.read_table(
                verified.path,
                columns=list(self.columns),
                filters=[("decision_date", "=", latest_value)],
            )
        except Exception as error:
            raise self._error(
                "FEATURE_CROSS_SECTION_READ_FAILED",
                "Latest feature cross-section cannot be read",
            ) from error
        frame = table.to_pandas()
        self._validate(frame, latest_value, manifest)
        return LatestFeatureCrossSection(
            frame=frame,
            as_of_date=latest_value,
            manifest=manifest,
            market=self.market,
        )

    def _validate(
        self, frame: Any, as_of_date: date, manifest: LatestFeatureManifest
    ) -> None:
        import pandas as pd

        if frame.empty or frame["symbol"].duplicated().any():
            raise self._error(
                "FEATURE_CROSS_SECTION_INVALID",
                "Latest feature cross-section must contain unique symbols",
            )
        expected = (
            manifest.MARKET == self.market
            and frame["decision_date"].eq(as_of_date).all()
            and frame["horizon"].eq(5).all()
            and frame["market"].eq(self.market).all()
            and frame["asset_type"].eq("COMMON_STOCK").all()
            and frame["feature_schema_hash"].eq(manifest.feature_schema_hash).all()
            and not frame["hard_fail"].any()
        )
        if not expected:
            raise self._error(
                "FEATURE_CROSS_SECTION_INVALID",
                f"Latest feature rows exceed the frozen {self.market} research scope",
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
            raise self._error(
                "FEATURE_POINT_IN_TIME_VIOLATION",
                "A feature is not available by its research decision time",
            )
        close = pd.to_numeric(frame["decision_close_price"], errors="coerce")
        adv20 = pd.to_numeric(frame["adv20_ntd"], errors="coerce")
        if (
            close.isna().any()
            or (close <= 0).any()
            or adv20.isna().any()
            or (adv20 <= 0).any()
        ):
            raise self._error(
                "FEATURE_COST_CONTEXT_INVALID",
                "Current price and ADV20 are required for auditable costs",
            )

    def _error(self, suffix: str, message: str) -> LatestFeatureSourceError:
        return LatestFeatureSourceError(f"{self.market}_{suffix}", message)


__all__ = [
    "LatestFeatureCrossSection",
    "LatestFeatureManifest",
    "LatestFeatureRepository",
    "LatestFeatureSourceError",
]
