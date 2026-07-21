"""Backward-compatible TWSE validation entry points."""

# pyright: reportAny=false, reportExplicitAny=false

from collections.abc import Mapping
from typing import Any

from .feature_artifact_validation import (
    metadata_from_schema as _metadata_from_schema,
    schema_digest,
    validate_metadata as _validate_metadata,
    validate_rows as _validate_rows,
    validate_schema as _validate_schema,
)


def metadata_from_schema(schema: Any) -> dict[str, str]:
    return _metadata_from_schema(schema, market="TWSE")


def validate_metadata(values: Mapping[str, str]) -> None:
    _validate_metadata(values, market="TWSE")


def validate_schema(schema: Any, metadata: Mapping[str, str]) -> None:
    _validate_schema(schema, metadata, market="TWSE")


def validate_rows(parquet: Any, metadata: Mapping[str, str]) -> None:
    _validate_rows(parquet, metadata, market="TWSE")


__all__ = [
    "metadata_from_schema",
    "schema_digest",
    "validate_metadata",
    "validate_rows",
    "validate_schema",
]
