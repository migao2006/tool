"""Frozen schema, metadata, and row-lineage checks for TWSE feature artifacts."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from collections.abc import Iterator, Mapping
from hashlib import sha256
import json
from typing import Any, cast

from src.features.twse_price_volume_schema import (
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
)

from .twse_archive_feature_contracts import (
    TWSE_ARCHIVE_FEATURE_DATASET_VERSION,
    TWSE_DECISION_TIME_POLICY_VERSION,
    dataset_snapshot_hash,
)
from .twse_archive_feature_parquet import twse_archive_feature_schema
from .twse_feature_artifact_contracts import (
    TWSE_FEATURE_ARTIFACT_AVAILABILITY_MODE,
    TWSE_FEATURE_ARTIFACT_LABEL_STATUS,
    TWSE_FEATURE_ARTIFACT_SYSTEM_STATUS,
    TWSE_FEATURE_ARTIFACT_USAGE_SCOPE,
    TwseFeatureArtifactReadError,
)


_METADATA_FIELDS = {
    "dataset.version": "dataset_version",
    "dataset.snapshot_sha256": "dataset_snapshot_sha256",
    "source_archive.snapshot_sha256": "source_archive_snapshot_sha256",
    "current_identity.snapshot_sha256": "current_identity_snapshot_sha256",
    "feature.schema_version": "feature_schema_version",
    "feature.schema_hash": "feature_schema_hash",
    "decision_time.policy_version": "decision_time_policy_version",
    "availability.mode": "availability_mode",
    "labels.status": "label_status",
    "usage.scope": "usage_scope",
    "system.status": "system_status",
    "horizon": "horizon",
}

_ROW_CONSTANTS: dict[str, object] = {
    "horizon": 5,
    "feature_schema_version": TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
    "feature_schema_hash": TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
    "decision_time_policy_version": TWSE_DECISION_TIME_POLICY_VERSION,
    "availability_mode": TWSE_FEATURE_ARTIFACT_AVAILABILITY_MODE,
    "point_in_time_audit_pass": False,
    "hard_fail": False,
    "label_status": TWSE_FEATURE_ARTIFACT_LABEL_STATUS,
    "usage_scope": TWSE_FEATURE_ARTIFACT_USAGE_SCOPE,
    "system_status": TWSE_FEATURE_ARTIFACT_SYSTEM_STATUS,
}

_LINEAGE_COLUMNS = (
    "archive_id",
    "source_object_key",
    "source_payload_sha256",
    "source_parquet_sha256",
)

_SHA256_CHARACTERS = frozenset("0123456789abcdef")


def schema_digest(schema: Any) -> str:
    fields = [
        {
            "name": field.name,
            "type": str(field.type),
            "nullable": bool(field.nullable),
        }
        for field in schema
    ]
    encoded = json.dumps(
        fields,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def metadata_from_schema(schema: Any) -> dict[str, str]:
    raw: Mapping[bytes, bytes] = schema.metadata or {}
    values: dict[str, str] = {}
    for key, field_name in _METADATA_FIELDS.items():
        encoded = raw.get(key.encode("ascii"))
        if encoded is None:
            raise TwseFeatureArtifactReadError(
                "TWSE_FEATURE_ARTIFACT_METADATA_MISSING",
                f"TWSE feature artifact metadata is missing {key}",
            )
        try:
            values[field_name] = encoded.decode("utf-8")
        except UnicodeDecodeError as error:
            raise TwseFeatureArtifactReadError(
                "TWSE_FEATURE_ARTIFACT_METADATA_INVALID",
                "TWSE feature artifact metadata is not valid UTF-8",
            ) from error
    return values


def validate_metadata(values: Mapping[str, str]) -> None:
    expected = {
        "dataset_version": TWSE_ARCHIVE_FEATURE_DATASET_VERSION,
        "feature_schema_version": TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
        "feature_schema_hash": TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
        "decision_time_policy_version": TWSE_DECISION_TIME_POLICY_VERSION,
        "availability_mode": TWSE_FEATURE_ARTIFACT_AVAILABILITY_MODE,
        "label_status": TWSE_FEATURE_ARTIFACT_LABEL_STATUS,
        "usage_scope": TWSE_FEATURE_ARTIFACT_USAGE_SCOPE,
        "system_status": TWSE_FEATURE_ARTIFACT_SYSTEM_STATUS,
        "horizon": "5",
    }
    if any(values.get(name) != value for name, value in expected.items()):
        raise TwseFeatureArtifactReadError(
            "TWSE_FEATURE_ARTIFACT_METADATA_INVALID",
            "TWSE feature artifact metadata exceeds the research-only contract",
        )
    calculated = dataset_snapshot_hash(
        source_archive_snapshot_sha256=values["source_archive_snapshot_sha256"],
        current_identity_snapshot_sha256=values["current_identity_snapshot_sha256"],
    )
    if calculated != values["dataset_snapshot_sha256"]:
        raise TwseFeatureArtifactReadError(
            "TWSE_FEATURE_ARTIFACT_INPUT_SNAPSHOT_MISMATCH",
            "Feature artifact input snapshots do not reproduce its dataset snapshot",
        )


def validate_schema(schema: Any, metadata: Mapping[str, str]) -> None:
    expected = twse_archive_feature_schema(
        dataset_snapshot_sha256=metadata["dataset_snapshot_sha256"],
        source_archive_snapshot_sha256=metadata["source_archive_snapshot_sha256"],
        current_identity_snapshot_sha256=metadata["current_identity_snapshot_sha256"],
    )
    if not schema.remove_metadata().equals(expected.remove_metadata()):
        raise TwseFeatureArtifactReadError(
            "TWSE_FEATURE_ARTIFACT_SCHEMA_INVALID",
            "TWSE feature artifact columns do not match the frozen feature schema",
        )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and not set(value).difference(_SHA256_CHARACTERS)
    )


def _batches(parquet: Any, columns: list[str]) -> Iterator[Any]:
    try:
        yield from parquet.iter_batches(batch_size=16_384, columns=columns)
    except Exception as error:
        raise TwseFeatureArtifactReadError(
            "TWSE_FEATURE_ARTIFACT_ROWS_INVALID",
            "Unable to read TWSE feature artifact provenance rows",
        ) from error


def validate_rows(parquet: Any, metadata: Mapping[str, str]) -> None:
    names = set(parquet.schema_arrow.names)
    columns = [
        "dataset_snapshot_sha256",
        "source_archive_snapshot_sha256",
        "current_identity_snapshot_sha256",
        *_ROW_CONSTANTS,
        *_LINEAGE_COLUMNS,
    ]
    missing = sorted(set(columns).difference(names))
    if missing:
        raise TwseFeatureArtifactReadError(
            "TWSE_FEATURE_ARTIFACT_SCHEMA_INVALID",
            "TWSE feature artifact is missing provenance columns",
        )
    expected_by_column: dict[str, object] = {
        **_ROW_CONSTANTS,
        "dataset_snapshot_sha256": metadata["dataset_snapshot_sha256"],
        "source_archive_snapshot_sha256": metadata["source_archive_snapshot_sha256"],
        "current_identity_snapshot_sha256": metadata[
            "current_identity_snapshot_sha256"
        ],
    }
    seen = 0
    for batch in _batches(parquet, columns):
        rows = batch.to_pylist()
        seen += len(rows)
        for row in cast(list[dict[str, object]], rows):
            if any(
                row.get(name) != value for name, value in expected_by_column.items()
            ):
                raise TwseFeatureArtifactReadError(
                    "TWSE_FEATURE_ARTIFACT_ROW_CONTRACT_MISMATCH",
                    "A TWSE feature row conflicts with artifact metadata",
                )
            archive_id = row.get("archive_id")
            if (
                isinstance(archive_id, bool)
                or not isinstance(archive_id, int)
                or archive_id <= 0
            ):
                raise TwseFeatureArtifactReadError(
                    "TWSE_FEATURE_ARTIFACT_LINEAGE_INVALID",
                    "A TWSE feature row has invalid archive lineage",
                )
            object_key = row.get("source_object_key")
            payload_hash = row.get("source_payload_sha256")
            parquet_hash = row.get("source_parquet_sha256")
            if (
                not isinstance(object_key, str)
                or not object_key.strip()
                or not _is_sha256(payload_hash)
                or not _is_sha256(parquet_hash)
            ):
                raise TwseFeatureArtifactReadError(
                    "TWSE_FEATURE_ARTIFACT_LINEAGE_INVALID",
                    "A TWSE feature row has incomplete archive lineage",
                )
    if seen != parquet.metadata.num_rows or seen <= 0:
        raise TwseFeatureArtifactReadError(
            "TWSE_FEATURE_ARTIFACT_ROW_COUNT_MISMATCH",
            "TWSE feature artifact row count does not match its footer",
        )


__all__ = [
    "metadata_from_schema",
    "schema_digest",
    "validate_metadata",
    "validate_rows",
    "validate_schema",
]
