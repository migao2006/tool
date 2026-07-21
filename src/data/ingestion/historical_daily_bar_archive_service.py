"""Archive one normalized FinMind symbol batch to verified private R2 Parquet.

The historical filename remains as a compatibility import for the original
daily-bar worker.  The implementation now supports the explicitly versioned
supplemental datasets without changing the existing daily-bar object keys.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import os
import re
from typing import Protocol, cast, final

from src.data.object_storage.r2_client import ObjectMetadata
from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError
from .historical_archive_contracts import HistoricalArchiveRequest
from .historical_archive_repository import HistoricalArchiveRepository
from .historical_benchmark_contracts import BENCHMARK_DATASET
from .historical_benchmark_parquet import serialize_historical_benchmark_parquet
from .historical_parquet_serializer import serialize_historical_parquet
from .historical_supplemental_contracts import SUPPLEMENTAL_DATASETS
from .historical_supplemental_parquet import (
    serialize_historical_supplemental_parquet,
)


_GIT_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")


class HistoricalArchiveObjectStore(Protocol):
    @property
    def bucket_name(self) -> str: ...

    def put_if_absent(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, str] | None = None,
    ) -> bool: ...

    def head(self, key: str) -> ObjectMetadata | None: ...

    def get(self, key: str) -> bytes: ...


@dataclass(frozen=True)
class HistoricalArchiveWriteResult:
    object_key: str
    created: bool
    content_sha256: str
    byte_size: int
    row_count: int


def _library_versions() -> dict[str, str]:
    values: dict[str, str] = {}
    for name in ("boto3", "pyarrow"):
        try:
            values[name] = version(name)
        except PackageNotFoundError:
            continue
    return values


def _git_commit() -> str | None:
    value = os.environ.get("GITHUB_SHA", "").strip().lower()
    return value if _GIT_COMMIT.fullmatch(value) else None


def _with_quarantine_issues(
    rows: Sequence[Mapping[str, object]],
    quarantine_rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    by_key: dict[str, list[dict[str, object]]] = {}
    for issue in quarantine_rows:
        landing_key = issue.get("landing_key")
        if not isinstance(landing_key, str) or not landing_key:
            raise IngestionError(
                "HISTORICAL_ARCHIVE_QUARANTINE_INVALID",
                "A quarantine issue is missing its landing key",
            )
        by_key.setdefault(landing_key, []).append(dict(issue))
    prepared: list[dict[str, object]] = []
    for row in rows:
        value = dict(row)
        landing_key = value.get("landing_key")
        value["archive_quarantine_issues"] = by_key.get(str(landing_key), [])
        prepared.append(value)
    return prepared


def _trade_date_bounds(rows: Sequence[Mapping[str, object]]) -> tuple[date, date]:
    parsed: list[date] = []
    for row in rows:
        value = row.get("trade_date")
        if value is None:
            continue
        try:
            parsed.append(
                value if type(value) is date else date.fromisoformat(str(value))
            )
        except ValueError as error:
            raise IngestionError(
                "HISTORICAL_ARCHIVE_TRADE_DATE_INVALID",
                "A normalized archive row contains an invalid trade date",
            ) from error
    if not parsed:
        raise IngestionError(
            "HISTORICAL_ARCHIVE_TRADE_DATE_MISSING",
            "A historical archive requires at least one parsed trade date",
        )
    return min(parsed), max(parsed)


def _first_observed_at(metadata: Mapping[str, str]) -> datetime:
    value = metadata.get("retrieved-at")
    try:
        observed = datetime.fromisoformat(value or "")
    except ValueError as error:
        raise IngestionError(
            "R2_ARCHIVE_METADATA_INVALID",
            "The R2 object is missing a valid retrieval timestamp",
        ) from error
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise IngestionError(
            "R2_ARCHIVE_METADATA_INVALID",
            "The R2 object retrieval timestamp is timezone-naive",
        )
    return observed


def _verified_object(
    *,
    store: HistoricalArchiveObjectStore,
    object_key: str,
    created: bool,
    artifact_sha256: str,
    artifact_size: int,
    expected_metadata: Mapping[str, str],
) -> ObjectMetadata:
    try:
        head = store.head(object_key)
    except Exception as error:
        raise IngestionError(
            "R2_ARCHIVE_HEAD_FAILED",
            "Unable to verify the archived R2 object",
        ) from error
    if head is None:
        raise IngestionError(
            "R2_ARCHIVE_OBJECT_MISSING",
            "R2 did not return the object after upload",
        )
    metadata = head.metadata
    content_sha256 = metadata.get("content-sha256", "")
    required_metadata = [
        "source-payload-sha256",
        "row-count",
        "schema-version",
        "compression",
        "scheduled-market",
        "asset-type",
    ]
    if "source-dataset" in expected_metadata:
        required_metadata.append("source-dataset")
    if "provider-code" in expected_metadata:
        required_metadata.append("provider-code")
    if (
        any(metadata.get(name) != expected_metadata[name] for name in required_metadata)
        or metadata.get("byte-size") != str(head.content_length)
        or head.content_type != "application/vnd.apache.parquet"
        or not re.fullmatch(r"[0-9a-f]{64}", content_sha256)
        or head.content_length <= 0
    ):
        raise IngestionError(
            "R2_ARCHIVE_METADATA_INVALID",
            "The R2 object metadata does not match the archive contract",
        )
    _ = _first_observed_at(metadata)
    if created:
        if metadata.get("retrieved-at") != expected_metadata["retrieved-at"]:
            raise IngestionError(
                "R2_ARCHIVE_METADATA_INVALID",
                "The uploaded R2 object has an unexpected retrieval timestamp",
            )
        if head.content_length != artifact_size or content_sha256 != artifact_sha256:
            raise IngestionError(
                "R2_ARCHIVE_INTEGRITY_MISMATCH",
                "The uploaded R2 object failed its size or checksum verification",
            )
    else:
        try:
            existing = store.get(object_key)
        except Exception as error:
            raise IngestionError(
                "R2_ARCHIVE_READ_FAILED",
                "Unable to verify the existing R2 object",
            ) from error
        if (
            len(existing) != head.content_length
            or sha256(existing).hexdigest() != content_sha256
        ):
            raise IngestionError(
                "R2_ARCHIVE_INTEGRITY_MISMATCH",
                "The existing R2 object failed its size or checksum verification",
            )
    return head


@final
class HistoricalDailyBarArchiveService:
    def __init__(
        self,
        *,
        store: HistoricalArchiveObjectStore,
        repository: HistoricalArchiveRepository,
        max_object_bytes: int = 50_000_000,
    ) -> None:
        if max_object_bytes <= 0:
            raise ValueError("max_object_bytes must be positive")
        self.store = store
        self.repository = repository
        self.max_object_bytes = max_object_bytes

    def archive(
        self,
        *,
        rows: Sequence[Mapping[str, object]],
        quarantine_rows: Sequence[Mapping[str, object]],
        payload: ProviderPayload,
        scheduled_market: str,
        asset_type: str,
        symbol: str,
        start_date: date,
        end_date: date,
        backfill_task_id: int | None,
    ) -> HistoricalArchiveWriteResult:
        request = HistoricalArchiveRequest(
            scheduled_market=scheduled_market,
            asset_type=asset_type,
            source_symbol=symbol,
            requested_start_date=start_date,
            requested_end_date=end_date,
            source_payload_sha256=payload.payload_sha256,
            retrieved_at=payload.retrieved_at,
            source_dataset=payload.dataset,
            provider_code=payload.provider,
        )
        prepared = _with_quarantine_issues(rows, quarantine_rows)
        if payload.dataset == "daily_bars":
            artifact = serialize_historical_parquet(prepared, request=request)
        elif payload.dataset == BENCHMARK_DATASET:
            artifact = serialize_historical_benchmark_parquet(
                prepared,
                request=request,
            )
        elif payload.dataset in SUPPLEMENTAL_DATASETS:
            artifact = serialize_historical_supplemental_parquet(
                prepared,
                request=request,
            )
        else:
            raise IngestionError(
                "HISTORICAL_ARCHIVE_SOURCE_INVALID",
                "The provider archive dataset is not supported",
            )
        object_metadata = artifact.object_metadata()
        if artifact.byte_size > self.max_object_bytes:
            raise IngestionError(
                "R2_ARCHIVE_OBJECT_TOO_LARGE",
                "The Parquet object exceeds the configured archive size limit",
            )
        try:
            created = self.store.put_if_absent(
                artifact.object_key,
                artifact.payload,
                content_type=artifact.content_type,
                metadata=object_metadata,
            )
        except Exception as error:
            raise IngestionError(
                "R2_ARCHIVE_WRITE_FAILED",
                "Unable to write the historical Parquet object to R2",
            ) from error
        head = _verified_object(
            store=self.store,
            object_key=artifact.object_key,
            created=created,
            artifact_sha256=artifact.content_sha256,
            artifact_size=artifact.byte_size,
            expected_metadata=object_metadata,
        )
        parsed_count = sum(row.get("parse_status") == "PARSED" for row in rows)
        quarantined_count = sum(
            row.get("parse_status") == "QUARANTINED" for row in rows
        )
        min_trade_date, max_trade_date = _trade_date_bounds(rows)
        reason_codes = sorted(
            {
                str(reason)
                for row in rows
                for reason in cast(Sequence[object], row.get("reason_codes", ()))
                if isinstance(reason, str) and reason
            }
        )
        content_sha256 = head.metadata["content-sha256"]
        archive_key = sha256(
            f"{self.store.bucket_name}\0{artifact.object_key}".encode("utf-8")
        ).hexdigest()
        manifest: dict[str, object] = {
            "archive_key": archive_key,
            "storage_provider": "CLOUDFLARE_R2",
            "bucket_name": self.store.bucket_name,
            "object_key": artifact.object_key,
            "object_etag": head.etag,
            "schema_version": artifact.schema_version,
            "provider_code": payload.provider,
            "source_dataset": payload.dataset,
            "source_version": payload.source_version,
            "source_symbol": symbol,
            "scheduled_market": request.scheduled_market,
            "asset_type": request.asset_type,
            "requested_start_date": start_date.isoformat(),
            "requested_end_date": end_date.isoformat(),
            "min_trade_date": min_trade_date.isoformat(),
            "max_trade_date": max_trade_date.isoformat(),
            "source_payload_hash": request.source_payload_sha256,
            "parquet_sha256": content_sha256,
            "byte_size": head.content_length,
            "row_count": artifact.row_count,
            "parsed_row_count": parsed_count,
            "quarantined_row_count": quarantined_count,
            "first_observed_at": _first_observed_at(head.metadata).isoformat(),
            "point_in_time_status": "UNVERIFIED",
            "usage_scope": "RAW_LANDING_ONLY",
            "system_status": "RESEARCH_ONLY",
            "reason_codes": reason_codes,
            "backfill_task_id": backfill_task_id,
            "git_commit": _git_commit(),
            "library_versions": _library_versions(),
        }
        self.repository.save(manifest)
        return HistoricalArchiveWriteResult(
            object_key=artifact.object_key,
            created=created,
            content_sha256=content_sha256,
            byte_size=head.content_length,
            row_count=artifact.row_count,
        )
