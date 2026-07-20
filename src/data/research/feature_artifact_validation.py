"""Frozen schema, metadata, and row checks for venue feature artifacts."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from collections.abc import Iterator, Mapping
from hashlib import sha256
import json
from math import isfinite
from typing import Any, cast

from .archive_feature_market import archive_feature_market_profile

from .archive_feature_contracts import dataset_snapshot_hash
from .archive_feature_parquet import archive_feature_schema
from .feature_artifact_contracts import (
    FEATURE_ARTIFACT_AVAILABILITY_MODE,
    FEATURE_ARTIFACT_LABEL_STATUS,
    FEATURE_ARTIFACT_SYSTEM_STATUS,
    FEATURE_ARTIFACT_USAGE_SCOPE,
    artifact_error,
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


def _row_constants(market: str) -> dict[str, object]:
    profile = archive_feature_market_profile(market)
    constants: dict[str, object] = {
        "horizon": 5,
        "feature_schema_version": profile.feature.schema_version,
        "feature_schema_hash": profile.feature.schema_hash,
        "decision_time_policy_version": profile.decision_time_policy_version,
        "availability_mode": FEATURE_ARTIFACT_AVAILABILITY_MODE,
        "point_in_time_audit_pass": False,
        "hard_fail": False,
        "label_status": FEATURE_ARTIFACT_LABEL_STATUS,
        "usage_scope": FEATURE_ARTIFACT_USAGE_SCOPE,
        "system_status": FEATURE_ARTIFACT_SYSTEM_STATUS,
    }
    # TWSE v1 sidecars predate venue row-scope enforcement. Keep their
    # read-back behavior compatible while freezing the new TPEX contract.
    if market == "TPEX":
        constants.update(market=profile.market, asset_type="COMMON_STOCK")
    return constants


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


def metadata_from_schema(schema: Any, *, market: str) -> dict[str, str]:
    raw: Mapping[bytes, bytes] = schema.metadata or {}
    values: dict[str, str] = {}
    for key, field_name in _METADATA_FIELDS.items():
        encoded = raw.get(key.encode("ascii"))
        if encoded is None:
            raise artifact_error(
                market,
                "METADATA_MISSING",
                f"{market} feature artifact metadata is missing {key}",
            )
        try:
            values[field_name] = encoded.decode("utf-8")
        except UnicodeDecodeError as error:
            raise artifact_error(
                market,
                "METADATA_INVALID",
                f"{market} feature artifact metadata is not valid UTF-8",
            ) from error
    return values


def validate_metadata(values: Mapping[str, str], *, market: str) -> None:
    profile = archive_feature_market_profile(market)
    expected = {
        "dataset_version": profile.dataset_version,
        "feature_schema_version": profile.feature.schema_version,
        "feature_schema_hash": profile.feature.schema_hash,
        "decision_time_policy_version": profile.decision_time_policy_version,
        "availability_mode": FEATURE_ARTIFACT_AVAILABILITY_MODE,
        "label_status": FEATURE_ARTIFACT_LABEL_STATUS,
        "usage_scope": FEATURE_ARTIFACT_USAGE_SCOPE,
        "system_status": FEATURE_ARTIFACT_SYSTEM_STATUS,
        "horizon": "5",
    }
    if any(values.get(name) != value for name, value in expected.items()):
        raise artifact_error(
            market,
            "METADATA_INVALID",
            f"{market} feature artifact metadata exceeds the research-only contract",
        )
    calculated = dataset_snapshot_hash(
        source_archive_snapshot_sha256=values["source_archive_snapshot_sha256"],
        current_identity_snapshot_sha256=values["current_identity_snapshot_sha256"],
        market=market,
    )
    if calculated != values["dataset_snapshot_sha256"]:
        raise artifact_error(
            market,
            "INPUT_SNAPSHOT_MISMATCH",
            "Feature artifact input snapshots do not reproduce its dataset snapshot",
        )


def validate_schema(
    schema: Any,
    metadata: Mapping[str, str],
    *,
    market: str,
) -> None:
    expected = archive_feature_schema(
        dataset_snapshot_sha256=metadata["dataset_snapshot_sha256"],
        source_archive_snapshot_sha256=metadata["source_archive_snapshot_sha256"],
        current_identity_snapshot_sha256=metadata["current_identity_snapshot_sha256"],
        market=market,
    )
    if not schema.remove_metadata().equals(expected.remove_metadata()):
        raise artifact_error(
            market,
            "SCHEMA_INVALID",
            f"{market} feature artifact columns do not match the frozen feature schema",
        )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and not set(value).difference(_SHA256_CHARACTERS)
    )


def _batches(parquet: Any, columns: list[str], *, market: str) -> Iterator[Any]:
    try:
        yield from parquet.iter_batches(batch_size=16_384, columns=columns)
    except Exception as error:
        raise artifact_error(
            market,
            "ROWS_INVALID",
            f"Unable to read {market} feature artifact provenance rows",
        ) from error


def validate_rows(
    parquet: Any,
    metadata: Mapping[str, str],
    *,
    market: str,
) -> None:
    row_constants = _row_constants(market)
    names = set(parquet.schema_arrow.names)
    columns = [
        "dataset_snapshot_sha256",
        "source_archive_snapshot_sha256",
        "current_identity_snapshot_sha256",
        *row_constants,
        *_LINEAGE_COLUMNS,
        "decision_close_price",
    ]
    missing = sorted(set(columns).difference(names))
    if missing:
        raise artifact_error(
            market,
            "SCHEMA_INVALID",
            f"{market} feature artifact is missing provenance columns",
        )
    expected_by_column: dict[str, object] = {
        **row_constants,
        "dataset_snapshot_sha256": metadata["dataset_snapshot_sha256"],
        "source_archive_snapshot_sha256": metadata["source_archive_snapshot_sha256"],
        "current_identity_snapshot_sha256": metadata[
            "current_identity_snapshot_sha256"
        ],
    }
    seen = 0
    for batch in _batches(parquet, columns, market=market):
        rows = batch.to_pylist()
        seen += len(rows)
        for row in cast(list[dict[str, object]], rows):
            if any(
                row.get(name) != value for name, value in expected_by_column.items()
            ):
                raise artifact_error(
                    market,
                    "ROW_CONTRACT_MISMATCH",
                    f"A {market} feature row conflicts with artifact metadata",
                )
            archive_id = row.get("archive_id")
            if (
                isinstance(archive_id, bool)
                or not isinstance(archive_id, int)
                or archive_id <= 0
            ):
                raise artifact_error(
                    market,
                    "LINEAGE_INVALID",
                    f"A {market} feature row has invalid archive lineage",
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
                raise artifact_error(
                    market,
                    "LINEAGE_INVALID",
                    f"A {market} feature row has incomplete archive lineage",
                )
            decision_close = row.get("decision_close_price")
            if (
                isinstance(decision_close, bool)
                or not isinstance(decision_close, (int, float))
                or not isfinite(float(decision_close))
                or float(decision_close) <= 0
            ):
                raise artifact_error(
                    market,
                    "DECISION_CLOSE_INVALID",
                    f"A {market} feature row has an invalid decision close",
                )
    if seen != parquet.metadata.num_rows or seen <= 0:
        raise artifact_error(
            market,
            "ROW_COUNT_MISMATCH",
            f"{market} feature artifact row count does not match its footer",
        )


__all__ = [
    "metadata_from_schema",
    "schema_digest",
    "validate_metadata",
    "validate_rows",
    "validate_schema",
]
