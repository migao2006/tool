from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from typing import Any

import pytest

from src.data.archive import HistoricalParquetReader
from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.historical_archive_repository import (
    HistoricalArchiveRepository,
)
from src.data.ingestion.historical_daily_bar_archive_service import (
    HistoricalDailyBarArchiveService,
    HistoricalArchiveWriteResult,
)
from src.data.ingestion.historical_daily_bar_normalizer import (
    normalize_historical_daily_bars,
)
from src.data.ingestion.historical_supplemental_normalizer import (
    normalize_historical_supplemental,
)
from src.data.object_storage.r2_client import ObjectMetadata
from src.data.object_storage.r2_client import R2Client, R2Settings
from src.data.providers.contracts import ProviderPayload


START_DATE = date(2020, 1, 1)
END_DATE = date(2020, 1, 31)


def _payload(
    *,
    retrieved_at: datetime = datetime(2026, 7, 19, tzinfo=timezone.utc),
) -> ProviderPayload:
    body = {
        "status": 200,
        "data": [
            {
                "date": "2020-01-02",
                "stock_id": "2330",
                "Trading_Volume": 34_000_000,
                "Trading_money": 11_500_000_000,
                "open": 332.5,
                "max": 339.0,
                "min": 332.5,
                "close": 339.0,
                "Trading_turnover": 30_115,
            }
        ],
    }
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return ProviderPayload(
        provider="FINMIND",
        dataset="daily_bars",
        source_version="api.v4",
        source_url="https://api.finmindtrade.com/api/v4/data",
        retrieved_at=retrieved_at,
        payload_sha256=sha256(encoded).hexdigest(),
        payload=body,
    )


def _fugle_adjusted_payload() -> ProviderPayload:
    body = {
        "symbol": "2330",
        "timeframe": "D",
        "data": [
            {
                "date": "2020-01-02",
                "open": 33.25,
                "high": 33.9,
                "low": 33.25,
                "close": 33.9,
                "volume": 34_000_000,
            }
        ],
    }
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return ProviderPayload(
        provider="FUGLE",
        dataset="adjusted_bars",
        source_version="marketdata.v1.0",
        source_url=(
            "https://api.fugle.tw/marketdata/v1.0/stock/"
            "historical/candles/2330?adjusted=true"
        ),
        retrieved_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        payload_sha256=sha256(encoded).hexdigest(),
        payload=body,
        request_metadata={
            "symbol": "2330",
            "adjusted": "true",
            "logical_dataset": "adjusted_bars",
            "remote_dataset": "historical_candles",
        },
    )


@dataclass
class StoredObject:
    body: bytes
    content_type: str
    metadata: dict[str, str]
    etag: str = '"archive-etag"'


class MemoryArchiveStore:
    bucket_name = "alpha-lens-archive"

    def __init__(self) -> None:
        self.objects: dict[str, StoredObject] = {}
        self.put_calls: list[str] = []
        self.head_calls: list[str] = []
        self.get_calls: list[str] = []
        self.put_error: Exception | None = None

    def put_if_absent(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, str] | None = None,
    ) -> bool:
        self.put_calls.append(key)
        if self.put_error is not None:
            raise self.put_error
        if key in self.objects:
            return False
        self.objects[key] = StoredObject(
            body=body,
            content_type=content_type,
            metadata=dict(metadata or {}),
        )
        return True

    def head(self, key: str) -> ObjectMetadata | None:
        self.head_calls.append(key)
        stored = self.objects.get(key)
        if stored is None:
            return None
        return ObjectMetadata(
            key=key,
            content_length=len(stored.body),
            etag=stored.etag,
            content_type=stored.content_type,
            metadata=dict(stored.metadata),
        )

    def get(self, key: str) -> bytes:
        self.get_calls.append(key)
        return self.objects[key].body


class MemoryReaderS3Client:
    def __init__(self, stored: StoredObject) -> None:
        self.stored = stored

    def head_object(self, **kwargs: Any) -> dict[str, object]:
        _ = kwargs
        return {
            "ContentLength": len(self.stored.body),
            "ContentType": self.stored.content_type,
            "Metadata": dict(self.stored.metadata),
            "ETag": self.stored.etag,
        }

    def get_object(self, **kwargs: Any) -> dict[str, object]:
        _ = kwargs
        return {"Body": BytesIO(self.stored.body)}


class RecordingManifestWriter:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    def upsert(
        self,
        table: str,
        rows: Sequence[Mapping[str, object]],
        *,
        on_conflict: str,
        select: str | None = None,
        return_rows: bool = False,
        preserve_existing: bool = False,
    ) -> list[dict[str, object]]:
        self.calls.append(
            {
                "table": table,
                "rows": [dict(row) for row in rows],
                "on_conflict": on_conflict,
                "select": select,
                "return_rows": return_rows,
                "preserve_existing": preserve_existing,
            }
        )
        if self.error is not None:
            raise self.error
        return []


def _service(
    store: MemoryArchiveStore,
    writer: RecordingManifestWriter,
) -> HistoricalDailyBarArchiveService:
    return HistoricalDailyBarArchiveService(
        store=store,
        repository=HistoricalArchiveRepository(writer),
    )


def _archive(
    service: HistoricalDailyBarArchiveService,
    *,
    source: ProviderPayload | None = None,
) -> HistoricalArchiveWriteResult:
    active_source = source or _payload()
    batch = normalize_historical_daily_bars(active_source)
    return service.archive(
        rows=batch.landing_rows,
        quarantine_rows=batch.quarantine_rows,
        payload=active_source,
        scheduled_market="TWSE",
        asset_type="COMMON_STOCK",
        symbol="2330",
        start_date=START_DATE,
        end_date=END_DATE,
        backfill_task_id=41,
    )


def _seed(store: MemoryArchiveStore) -> HistoricalArchiveWriteResult:
    return _archive(_service(store, RecordingManifestWriter()))


def test_upload_and_head_verification_save_compact_manifest() -> None:
    store = MemoryArchiveStore()
    writer = RecordingManifestWriter()

    result = _archive(_service(store, writer))

    assert result.created
    assert store.put_calls == store.head_calls == [result.object_key]
    assert store.get_calls == []
    stored = store.objects[result.object_key]
    assert result.byte_size == len(stored.body)
    assert result.content_sha256 == sha256(stored.body).hexdigest()
    assert stored.metadata["content-sha256"] == result.content_sha256
    assert stored.metadata["byte-size"] == str(result.byte_size)

    assert len(writer.calls) == 1
    call = writer.calls[0]
    assert call["table"] == "historical_archive_objects"
    manifest = call["rows"][0]
    assert manifest["object_key"] == result.object_key
    assert manifest["parquet_sha256"] == result.content_sha256
    assert manifest["backfill_task_id"] == 41
    assert manifest["system_status"] == "RESEARCH_ONLY"
    assert "source_row" not in manifest


def test_fugle_adjusted_archive_records_provider_without_changing_daily_keys() -> None:
    store = MemoryArchiveStore()
    writer = RecordingManifestWriter()
    payload = _fugle_adjusted_payload()
    batch = normalize_historical_supplemental(payload)

    result = _service(store, writer).archive(
        rows=batch.landing_rows,
        quarantine_rows=batch.quarantine_rows,
        payload=payload,
        scheduled_market="TWSE",
        asset_type="COMMON_STOCK",
        symbol="2330",
        start_date=START_DATE,
        end_date=END_DATE,
        backfill_task_id=None,
    )

    assert result.object_key.startswith("raw/v1/provider=fugle/dataset=adjusted_bars/")
    assert store.objects[result.object_key].metadata["provider-code"] == "FUGLE"
    manifest_rows = writer.calls[0]["rows"]
    assert isinstance(manifest_rows, list)
    manifest = manifest_rows[0]
    assert isinstance(manifest, dict)
    assert manifest["provider_code"] == "FUGLE"
    assert manifest["source_dataset"] == "adjusted_bars"
    assert manifest["usage_scope"] == "RAW_LANDING_ONLY"
    daily_key = _seed(MemoryArchiveStore()).object_key
    assert daily_key.startswith("raw/v1/provider=finmind/dataset=daily_bars/")

    settings = R2Settings(
        account_id="account123",
        access_key_id="access-key",
        secret_access_key="secret-key",
        bucket_name=store.bucket_name,
    )
    verified = HistoricalParquetReader(
        R2Client(
            settings,
            s3_client=MemoryReaderS3Client(store.objects[result.object_key]),
        )
    ).read(manifest)
    assert verified.row_count == 1
    assert verified.manifest.provider_code == "FUGLE"
    assert verified.rows[0]["source_code"] == "FUGLE"


def test_existing_object_is_downloaded_and_hash_verified_before_manifest() -> None:
    store = MemoryArchiveStore()
    seeded = _seed(store)
    store.head_calls.clear()
    store.get_calls.clear()
    writer = RecordingManifestWriter()

    result = _archive(_service(store, writer))

    assert not result.created
    assert result.object_key == seeded.object_key
    assert store.head_calls == store.get_calls == [seeded.object_key]
    assert len(writer.calls) == 1


def test_existing_same_payload_with_new_retrieval_time_can_recover_manifest() -> None:
    store = MemoryArchiveStore()
    with pytest.raises(RuntimeError, match="initial manifest failure"):
        _archive(
            _service(
                store,
                RecordingManifestWriter(error=RuntimeError("initial manifest failure")),
            )
        )
    object_key = next(iter(store.objects))
    stored = store.objects[object_key]
    stored_retrieved_at = stored.metadata["retrieved-at"]
    stored_sha256 = stored.metadata["content-sha256"]
    writer = RecordingManifestWriter()
    retry_payload = _payload(retrieved_at=datetime(2026, 7, 20, tzinfo=timezone.utc))

    result = _archive(_service(store, writer), source=retry_payload)

    assert not result.created
    assert result.object_key == object_key
    assert result.content_sha256 == stored_sha256
    assert store.get_calls[-1] == object_key
    manifest = writer.calls[0]["rows"][0]
    assert manifest["first_observed_at"] == stored_retrieved_at


def test_metadata_mismatch_fails_closed_without_manifest() -> None:
    store = MemoryArchiveStore()
    seeded = _seed(store)
    store.objects[seeded.object_key].metadata["row-count"] = "999"
    writer = RecordingManifestWriter()

    with pytest.raises(IngestionError) as captured:
        _archive(_service(store, writer))

    assert captured.value.reason_code == "R2_ARCHIVE_METADATA_INVALID"
    assert writer.calls == []


def test_existing_object_hash_mismatch_fails_closed_without_manifest() -> None:
    store = MemoryArchiveStore()
    seeded = _seed(store)
    stored = store.objects[seeded.object_key]
    stored.body = bytes([stored.body[0] ^ 1]) + stored.body[1:]
    writer = RecordingManifestWriter()

    with pytest.raises(IngestionError) as captured:
        _archive(_service(store, writer))

    assert captured.value.reason_code == "R2_ARCHIVE_INTEGRITY_MISMATCH"
    assert store.get_calls[-1] == seeded.object_key
    assert writer.calls == []


def test_write_failure_never_saves_manifest() -> None:
    store = MemoryArchiveStore()
    store.put_error = OSError("R2 unavailable")
    writer = RecordingManifestWriter()

    with pytest.raises(IngestionError) as captured:
        _archive(_service(store, writer))

    assert captured.value.reason_code == "R2_ARCHIVE_WRITE_FAILED"
    assert store.head_calls == []
    assert writer.calls == []


def test_repository_failure_propagates_after_verified_object() -> None:
    class RepositoryFailure(RuntimeError):
        pass

    failure = RepositoryFailure("manifest unavailable")
    store = MemoryArchiveStore()
    writer = RecordingManifestWriter(error=failure)

    with pytest.raises(RepositoryFailure) as captured:
        _archive(_service(store, writer))

    assert captured.value is failure
    assert len(store.objects) == 1
    assert len(store.head_calls) == 1
    assert len(writer.calls) == 1
