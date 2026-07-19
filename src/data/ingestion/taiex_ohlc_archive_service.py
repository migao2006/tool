"""Write and read-back verify one immutable monthly TAIEX OHLC object."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import os
import re
from typing import final

from src.data.archive import HistoricalArchiveReadError, HistoricalParquetReader
from src.data.archive.contracts import HistoricalArchiveManifest
from src.data.object_storage.r2_client import R2Client

from .contracts import IngestionError
from .historical_archive_repository import HistoricalArchiveRepository
from .historical_daily_bar_archive_service import HistoricalArchiveWriteResult
from .taiex_ohlc_archive import build_taiex_ohlc_archive, build_taiex_ohlc_manifest
from .taiex_ohlc_contracts import NormalizedTaiexOhlcBatch


_GIT_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")


def _library_versions() -> dict[str, str]:
    values: dict[str, str] = {}
    for package in ("boto3", "pyarrow"):
        try:
            values[package] = version(package)
        except PackageNotFoundError:
            continue
    return values


def _git_commit() -> str | None:
    value = os.environ.get("GITHUB_SHA", "").strip().lower()
    return value if _GIT_COMMIT.fullmatch(value) else None


def _observed_at(value: str | None) -> datetime:
    try:
        parsed = datetime.fromisoformat(value or "")
    except ValueError as error:
        raise IngestionError(
            "TAIEX_OHLC_R2_METADATA_INVALID",
            "TAIEX OHLC object is missing a valid retrieval timestamp",
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise IngestionError(
            "TAIEX_OHLC_R2_METADATA_INVALID",
            "TAIEX OHLC object retrieval timestamp is timezone-naive",
        )
    return parsed.astimezone(timezone.utc)


def _manifest_row(
    manifest: HistoricalArchiveManifest,
    *,
    backfill_task_id: int,
) -> dict[str, object]:
    row = asdict(manifest)
    row.update(
        {
            "requested_start_date": manifest.requested_start_date.isoformat(),
            "requested_end_date": manifest.requested_end_date.isoformat(),
            "min_trade_date": manifest.min_trade_date.isoformat(),
            "max_trade_date": manifest.max_trade_date.isoformat(),
        }
    )
    row["first_observed_at"] = manifest.first_observed_at.isoformat()
    row["reason_codes"] = list(manifest.reason_codes)
    row["backfill_task_id"] = backfill_task_id
    row["git_commit"] = _git_commit()
    row["library_versions"] = _library_versions()
    return row


@final
class TaiexOhlcArchiveService:
    def __init__(
        self,
        *,
        store: R2Client,
        repository: HistoricalArchiveRepository,
        max_object_bytes: int = 10_000_000,
    ) -> None:
        if max_object_bytes <= 0:
            raise ValueError("max_object_bytes must be positive")
        self.store = store
        self.repository = repository
        self.max_object_bytes = max_object_bytes

    def archive(
        self,
        batch: NormalizedTaiexOhlcBatch,
        *,
        backfill_task_id: int,
    ) -> HistoricalArchiveWriteResult:
        artifact = build_taiex_ohlc_archive(batch)
        if artifact.byte_size > self.max_object_bytes:
            raise IngestionError(
                "TAIEX_OHLC_ARCHIVE_OBJECT_TOO_LARGE",
                "TAIEX OHLC Parquet exceeds the configured object limit",
            )
        try:
            created = self.store.put_if_absent(
                artifact.object_key,
                artifact.payload,
                content_type=artifact.content_type,
                metadata=artifact.object_metadata(),
            )
            head = self.store.head(artifact.object_key)
        except Exception as error:
            raise IngestionError(
                "TAIEX_OHLC_R2_WRITE_FAILED",
                "TAIEX OHLC object could not be written and inspected",
            ) from error
        if head is None:
            raise IngestionError(
                "TAIEX_OHLC_R2_OBJECT_MISSING",
                "TAIEX OHLC object is missing after conditional upload",
            )

        manifest = build_taiex_ohlc_manifest(
            batch,
            artifact,
            bucket_name=self.store.bucket_name,
            object_etag=head.etag,
        )
        if not created:
            content_sha256 = head.metadata.get("content-sha256", "")
            row_count = head.metadata.get("row-count", "")
            if (
                not re.fullmatch(r"[0-9a-f]{64}", content_sha256)
                or row_count != str(len(batch.rows))
            ):
                raise IngestionError(
                    "TAIEX_OHLC_R2_METADATA_INVALID",
                    "Existing TAIEX OHLC object does not match the monthly batch",
                )
            manifest = replace(
                manifest,
                parquet_sha256=content_sha256,
                byte_size=head.content_length,
                first_observed_at=_observed_at(
                    head.metadata.get("retrieved-at")
                ),
            )
        try:
            verified = HistoricalParquetReader(self.store).read(manifest)
        except HistoricalArchiveReadError as error:
            raise IngestionError(error.reason_code, str(error)) from error
        if verified.row_count != len(batch.rows):
            raise IngestionError(
                "TAIEX_OHLC_ARCHIVE_ROW_COUNT_MISMATCH",
                "Verified TAIEX OHLC rows do not match the provider response",
            )
        self.repository.save(
            _manifest_row(manifest, backfill_task_id=backfill_task_id)
        )
        return HistoricalArchiveWriteResult(
            object_key=manifest.object_key,
            created=created,
            content_sha256=manifest.parquet_sha256,
            byte_size=manifest.byte_size,
            row_count=manifest.row_count,
        )
