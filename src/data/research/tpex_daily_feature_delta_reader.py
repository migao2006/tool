"""Fail-closed read-back verification for TPEX feature deltas."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any, cast

from src.features.tpex_price_volume_schema import (
    TPEX_PRICE_VOLUME_FEATURE_NAMES,
    TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
)

from .feature_artifact_validation import schema_digest
from .tpex_daily_feature_delta_artifact import (
    _modules,
    tpex_daily_feature_delta_schema,
)
from .tpex_daily_feature_delta_contracts import (
    TpexDailyFeatureDeltaError,
    TpexDailyFeatureDeltaManifest,
)
from .tpex_daily_feature_delta_verification import (
    VerifiedTpexDailyFeatureDelta,
    verified_tpex_daily_feature_delta,
)


_METADATA = {
    "dataset.version": "dataset_version",
    "dataset.snapshot_sha256": "dataset_snapshot_sha256",
    "source_archive.snapshot_sha256": "source_archive_snapshot_sha256",
    "current_identity.snapshot_sha256": "current_identity_snapshot_sha256",
    "daily_bar.snapshot_sha256": "daily_bar_snapshot_sha256",
    "delta.as_of_date": "as_of_date",
    "feature.schema_version": "feature_schema_version",
    "feature.schema_hash": "feature_schema_hash",
    "decision_time.policy_version": "decision_time_policy_version",
    "availability.mode": "availability_mode",
    "labels.status": "label_status",
    "usage.scope": "usage_scope",
    "system.status": "system_status",
    "point_in_time.status": "point_in_time_status",
    "horizon": "horizon",
}


class TpexDailyFeatureDeltaReader:
    def manifest_from_parquet(self, path: str | Path) -> TpexDailyFeatureDeltaManifest:
        artifact_path = Path(path)
        digest = sha256()
        byte_size = 0
        try:
            with artifact_path.open("rb") as source:
                while block := source.read(1024 * 1024):
                    digest.update(block)
                    byte_size += len(block)
            _, pq = _modules()
            parquet = pq.ParquetFile(artifact_path)
        except Exception as error:
            raise self._error(
                "READ_FAILED", "TPEX feature delta is unreadable"
            ) from error
        if byte_size <= 0 or parquet.metadata.num_rows <= 0:
            raise self._error("EMPTY", "TPEX feature delta must contain rows")
        metadata = self._metadata(parquet.schema_arrow)
        try:
            as_of_date = date.fromisoformat(metadata["as_of_date"])
        except ValueError as error:
            raise self._error("METADATA_INVALID", "Delta date is invalid") from error
        expected_schema = tpex_daily_feature_delta_schema(
            dataset_snapshot_sha256=metadata["dataset_snapshot_sha256"],
            source_archive_snapshot_sha256=metadata["source_archive_snapshot_sha256"],
            current_identity_snapshot_sha256=metadata[
                "current_identity_snapshot_sha256"
            ],
            daily_bar_snapshot_sha256=metadata["daily_bar_snapshot_sha256"],
            as_of_date=as_of_date,
        )
        if not parquet.schema_arrow.remove_metadata().equals(
            expected_schema.remove_metadata()
        ):
            raise self._error("SCHEMA_INVALID", "Delta columns do not match schema")
        manifest = TpexDailyFeatureDeltaManifest(
            parquet_sha256=digest.hexdigest(),
            parquet_schema_sha256=schema_digest(parquet.schema_arrow),
            byte_size=byte_size,
            row_count=parquet.metadata.num_rows,
            dataset_snapshot_sha256=metadata["dataset_snapshot_sha256"],
            source_archive_snapshot_sha256=metadata["source_archive_snapshot_sha256"],
            current_identity_snapshot_sha256=metadata[
                "current_identity_snapshot_sha256"
            ],
            daily_bar_snapshot_sha256=metadata["daily_bar_snapshot_sha256"],
            as_of_date=as_of_date,
            dataset_version=metadata["dataset_version"],
            feature_schema_version=metadata["feature_schema_version"],
            feature_schema_hash=metadata["feature_schema_hash"],
            decision_time_policy_version=metadata["decision_time_policy_version"],
            availability_mode=metadata["availability_mode"],
            horizon=int(metadata["horizon"]),
            label_status=metadata["label_status"],
            usage_scope=metadata["usage_scope"],
            system_status=metadata["system_status"],
            point_in_time_status=metadata["point_in_time_status"],
        )
        self._validate_rows(parquet, manifest)
        return manifest

    def verify(
        self,
        path: str | Path,
        manifest: TpexDailyFeatureDeltaManifest,
    ) -> VerifiedTpexDailyFeatureDelta:
        if self.manifest_from_parquet(path) != manifest:
            raise self._error("MANIFEST_MISMATCH", "Delta bytes changed after manifest")
        return verified_tpex_daily_feature_delta(Path(path), manifest)

    def _metadata(self, schema: Any) -> dict[str, str]:
        raw = cast(Mapping[bytes, bytes], schema.metadata or {})
        values: dict[str, str] = {}
        for key, field_name in _METADATA.items():
            encoded = raw.get(key.encode("ascii"))
            if encoded is None:
                raise self._error("METADATA_MISSING", f"Delta metadata lacks {key}")
            try:
                values[field_name] = encoded.decode("utf-8")
            except UnicodeDecodeError as error:
                raise self._error(
                    "METADATA_INVALID", "Delta metadata is invalid"
                ) from error
        if raw.get(b"artifact.kind") != b"DAILY_FEATURE_DELTA":
            raise self._error("METADATA_INVALID", "Artifact kind is not a delta")
        return values

    def _validate_rows(
        self,
        parquet: Any,
        manifest: TpexDailyFeatureDeltaManifest,
    ) -> None:
        columns = [
            "dataset_snapshot_sha256",
            "source_archive_snapshot_sha256",
            "current_identity_snapshot_sha256",
            "daily_bar_snapshot_sha256",
            "archive_id",
            "source_payload_sha256",
            "source_parquet_sha256",
            "symbol",
            "market",
            "asset_type",
            "decision_date",
            "horizon",
            "feature_schema_hash",
            "hard_fail",
            "point_in_time_audit_pass",
            "decision_close_price",
            "source_daily_bar_id",
            "source_daily_source_id",
            "source_daily_version",
            "source_daily_available_at",
            *TPEX_PRICE_VOLUME_FEATURE_NAMES,
        ]
        rows = cast(
            list[dict[str, object]],
            parquet.read(columns=columns).to_pylist(),
        )
        if len(rows) != manifest.row_count or len(
            {row["symbol"] for row in rows}
        ) != len(rows):
            raise self._error("ROWS_INVALID", "Delta rows are not unique")
        constants = {
            "dataset_snapshot_sha256": manifest.dataset_snapshot_sha256,
            "source_archive_snapshot_sha256": (manifest.source_archive_snapshot_sha256),
            "current_identity_snapshot_sha256": (
                manifest.current_identity_snapshot_sha256
            ),
            "daily_bar_snapshot_sha256": manifest.daily_bar_snapshot_sha256,
            "market": "TPEX",
            "asset_type": "COMMON_STOCK",
            "decision_date": manifest.as_of_date,
            "horizon": 5,
            "feature_schema_hash": TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
            "hard_fail": False,
            "point_in_time_audit_pass": False,
        }
        daily_ids: list[int] = []
        daily_source_ids: set[int] = set()
        daily_versions: set[str] = set()
        for row in rows:
            if any(row.get(name) != value for name, value in constants.items()):
                raise self._error("ROW_CONTRACT_MISMATCH", "Delta row scope is invalid")
            integers = (
                row.get("archive_id"),
                row.get("source_daily_bar_id"),
                row.get("source_daily_source_id"),
            )
            if any(
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
                for value in integers
            ):
                raise self._error("LINEAGE_INVALID", "Delta lineage ID is invalid")
            daily_id = cast(int, row["source_daily_bar_id"])
            daily_source_id = cast(int, row["source_daily_source_id"])
            daily_ids.append(daily_id)
            daily_source_ids.add(daily_source_id)
            source_version = str(row.get("source_daily_version") or "").strip()
            if not source_version:
                raise self._error("LINEAGE_INVALID", "Delta source version is missing")
            daily_versions.add(source_version)
            source_available_at = row.get("source_daily_available_at")
            if (
                not isinstance(source_available_at, datetime)
                or source_available_at.tzinfo is None
                or source_available_at.utcoffset() is None
            ):
                raise self._error(
                    "LINEAGE_INVALID", "Delta source availability is invalid"
                )
            digests = (
                row.get("source_payload_sha256"),
                row.get("source_parquet_sha256"),
            )
            if any(
                not isinstance(value, str)
                or len(value) != 64
                or set(value).difference("0123456789abcdef")
                for value in digests
            ):
                raise self._error("LINEAGE_INVALID", "Archive digest is invalid")
            numeric = (
                row.get("decision_close_price"),
                *(row.get(name) for name in TPEX_PRICE_VOLUME_FEATURE_NAMES),
            )
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(float(value))
                for value in numeric
            ):
                raise self._error("FEATURE_VALUE_INVALID", "Delta feature is invalid")
        if (
            len(set(daily_ids)) != len(daily_ids)
            or len(daily_source_ids) != 1
            or len(daily_versions) != 1
        ):
            raise self._error(
                "LINEAGE_INVALID", "Delta rows do not share a unique source revision"
            )

    @staticmethod
    def _error(suffix: str, message: str) -> TpexDailyFeatureDeltaError:
        return TpexDailyFeatureDeltaError(f"TPEX_DAILY_FEATURE_DELTA_{suffix}", message)


__all__ = ["TpexDailyFeatureDeltaReader"]
