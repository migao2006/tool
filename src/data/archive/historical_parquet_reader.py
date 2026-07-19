"""Read and fully verify one manifest-bound historical Parquet object."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
from typing import final

from src.data.ingestion.historical_archive_contracts import (
    HISTORICAL_ARCHIVE_COMPRESSION,
    HISTORICAL_ARCHIVE_CONTENT_TYPE,
)
from src.data.object_storage.r2_client import R2Client

from .contracts import (
    HistoricalArchiveManifest,
    HistoricalArchiveReadError,
    VerifiedHistoricalArchive,
)
from .historical_parquet_validation import validate_historical_parquet


def _fail(reason_code: str, message: str) -> HistoricalArchiveReadError:
    return HistoricalArchiveReadError(reason_code, message)


def _verify_head(
    *,
    client: R2Client,
    manifest: HistoricalArchiveManifest,
) -> None:
    try:
        head = client.head(manifest.object_key)
    except Exception as error:
        raise _fail(
            "HISTORICAL_ARCHIVE_R2_HEAD_FAILED",
            "Unable to inspect the historical R2 object",
        ) from error
    if head is None:
        raise _fail(
            "HISTORICAL_ARCHIVE_R2_OBJECT_MISSING",
            "The historical R2 object referenced by the manifest is missing",
        )
    expected_metadata = {
        "content-sha256": manifest.parquet_sha256,
        "byte-size": str(manifest.byte_size),
        "row-count": str(manifest.row_count),
        "schema-version": manifest.schema_version,
        "compression": HISTORICAL_ARCHIVE_COMPRESSION.lower(),
        "scheduled-market": manifest.scheduled_market,
        "asset-type": manifest.asset_type,
        "source-payload-sha256": manifest.source_payload_hash,
    }
    if manifest.source_dataset != "daily_bars":
        expected_metadata["source-dataset"] = manifest.source_dataset
    if (
        head.content_length != manifest.byte_size
        or head.content_type != HISTORICAL_ARCHIVE_CONTENT_TYPE
        or any(
            head.metadata.get(key) != value for key, value in expected_metadata.items()
        )
        or (manifest.object_etag is not None and head.etag != manifest.object_etag)
    ):
        raise _fail(
            "HISTORICAL_ARCHIVE_R2_METADATA_MISMATCH",
            "R2 object metadata does not match the archive manifest",
        )
    retrieved_at = head.metadata.get("retrieved-at")
    try:
        parsed = datetime.fromisoformat(retrieved_at or "")
    except ValueError as error:
        raise _fail(
            "HISTORICAL_ARCHIVE_R2_METADATA_MISMATCH",
            "R2 object metadata contains an invalid retrieval timestamp",
        ) from error
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.astimezone(timezone.utc) != manifest.first_observed_at
    ):
        raise _fail(
            "HISTORICAL_ARCHIVE_R2_METADATA_MISMATCH",
            "R2 object retrieval timestamp does not match the archive manifest",
        )


def _download(client: R2Client, manifest: HistoricalArchiveManifest) -> bytes:
    try:
        payload = client.get(manifest.object_key)
    except Exception as error:
        raise _fail(
            "HISTORICAL_ARCHIVE_R2_READ_FAILED",
            "Unable to download the historical R2 object",
        ) from error
    if (
        len(payload) != manifest.byte_size
        or sha256(payload).hexdigest() != manifest.parquet_sha256
    ):
        raise _fail(
            "HISTORICAL_ARCHIVE_CONTENT_MISMATCH",
            "Historical archive bytes failed size or SHA-256 verification",
        )
    return payload


@final
class HistoricalParquetReader:
    """Release rows only after R2, manifest, schema, and content checks pass."""

    def __init__(self, client: R2Client) -> None:
        self.client = client

    def read(
        self,
        manifest: HistoricalArchiveManifest | Mapping[str, object],
    ) -> VerifiedHistoricalArchive:
        parsed_manifest = (
            manifest
            if isinstance(manifest, HistoricalArchiveManifest)
            else HistoricalArchiveManifest.from_mapping(manifest)
        )
        if parsed_manifest.bucket_name != self.client.bucket_name:
            raise _fail(
                "HISTORICAL_ARCHIVE_BUCKET_MISMATCH",
                "Archive manifest references a different R2 bucket",
            )
        _verify_head(client=self.client, manifest=parsed_manifest)
        payload = _download(self.client, parsed_manifest)
        rows = validate_historical_parquet(payload, parsed_manifest)
        return VerifiedHistoricalArchive(
            manifest=parsed_manifest,
            rows=rows,
            content_sha256=parsed_manifest.parquet_sha256,
            byte_size=parsed_manifest.byte_size,
            row_count=parsed_manifest.row_count,
            schema_version=parsed_manifest.schema_version,
        )
