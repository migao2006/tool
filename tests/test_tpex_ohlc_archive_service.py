from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import cast, final

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.historical_archive_repository import (
    HistoricalArchiveRepository,
)
from src.data.ingestion.tpex_ohlc_archive_service import TpexOhlcArchiveService
from src.data.ingestion.tpex_ohlc_normalizer import normalize_tpex_monthly_ohlc
from src.data.object_storage.r2_client import ObjectMetadata, R2Client
from src.data.providers.contracts import ProviderPayload
from src.data.providers.tpex import (
    TPEX_MONTHLY_OHLC_DATASET,
    TPEX_MONTHLY_OHLC_SOURCE_VERSION,
)


RETRIEVED_AT = datetime(2026, 7, 20, 5, tzinfo=timezone.utc)


def _payload(*, retrieved_at: datetime = RETRIEVED_AT) -> ProviderPayload:
    body = {
        "date": "20240101",
        "tables": [
            {
                "title": "Historical Data of TPEx Index",
                "date": "2024/01",
                "totalCount": 2,
                "fields": ["Date", "Open", "High", "Low", "Close", "Change(%)"],
                "data": [
                    ["2024/01/02", "234.13", "234.96", "232.69", "233.23", "-0.78"],
                    ["2024/01/03", "232.94", "232.94", "230.69", "231.05", "-2.18"],
                ],
                "summary": [],
                "notes": [],
            }
        ],
        "stat": "ok",
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return ProviderPayload(
        provider="TPEX",
        dataset=TPEX_MONTHLY_OHLC_DATASET,
        source_version=TPEX_MONTHLY_OHLC_SOURCE_VERSION,
        source_url=(
            "https://www.tpex.org.tw/www/en-us/indexInfo/inx"
            "?date=2024%2F01%2F01&response=json"
        ),
        retrieved_at=retrieved_at,
        payload_sha256=sha256(encoded).hexdigest(),
        payload=body,
        request_metadata={
            "requested_month": "2024-01",
            "request_date": "2024/01/01",
            "calendar": "GREGORIAN",
            "language": "en",
            "available_at_policy": "first_project_retrieval_only",
        },
    )


@dataclass
class StoredObject:
    body: bytes
    content_type: str
    metadata: dict[str, str]
    etag: str = '"tpex-etag"'


@final
class MemoryArchiveStore:
    bucket_name: str = "alpha-lens-archive"

    def __init__(self) -> None:
        self.objects: dict[str, StoredObject] = {}
        self.get_calls: list[str] = []

    def put_if_absent(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, str] | None = None,
    ) -> bool:
        if key in self.objects:
            return False
        self.objects[key] = StoredObject(
            body=body,
            content_type=content_type,
            metadata=dict(metadata or {}),
        )
        return True

    def head(self, key: str) -> ObjectMetadata | None:
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


@final
class RecordingWriter:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

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
        assert table == "historical_archive_objects"
        assert on_conflict == "archive_key"
        assert preserve_existing
        assert select is None and not return_rows
        self.rows.extend(dict(row) for row in rows)
        return []


def _service(
    store: MemoryArchiveStore,
    writer: RecordingWriter,
) -> TpexOhlcArchiveService:
    return TpexOhlcArchiveService(
        store=cast(R2Client, cast(object, store)),
        repository=HistoricalArchiveRepository(writer),
    )


def test_archive_is_immutable_read_back_verified_and_manifest_only() -> None:
    store = MemoryArchiveStore()
    writer = RecordingWriter()
    batch = normalize_tpex_monthly_ohlc(_payload())

    result = _service(store, writer).archive(batch, backfill_task_id=91)

    assert result.created
    assert store.get_calls == [result.object_key]
    assert len(writer.rows) == 1
    manifest = writer.rows[0]
    assert manifest["provider_code"] == "TPEX"
    assert manifest["source_dataset"] == "tpex_price_index_ohlc"
    assert manifest["schema_version"] == "tpex_price_index_ohlc.v1"
    assert manifest["source_symbol"] == "TPEX_INDEX"
    assert manifest["backfill_task_id"] == 91
    assert manifest["point_in_time_status"] == "UNVERIFIED"
    assert manifest["usage_scope"] == "RAW_LANDING_ONLY"
    assert manifest["system_status"] == "RESEARCH_ONLY"
    reason_codes = manifest["reason_codes"]
    assert isinstance(reason_codes, list)
    assert "PRICE_INDEX_NOT_TOTAL_RETURN" in reason_codes
    assert "source_row" not in manifest


def test_same_payload_retry_reuses_object_and_original_observation_time() -> None:
    store = MemoryArchiveStore()
    first_writer = RecordingWriter()
    first_batch = normalize_tpex_monthly_ohlc(_payload())
    first = _service(store, first_writer).archive(first_batch, backfill_task_id=91)
    original_observed_at = first_writer.rows[0]["first_observed_at"]
    retry_writer = RecordingWriter()
    retry_batch = normalize_tpex_monthly_ohlc(
        _payload(retrieved_at=datetime(2026, 7, 21, tzinfo=timezone.utc))
    )

    retry = _service(store, retry_writer).archive(
        retry_batch,
        backfill_task_id=91,
    )

    assert not retry.created
    assert retry.object_key == first.object_key
    assert retry_writer.rows[0]["first_observed_at"] == original_observed_at
    assert store.get_calls[-1] == first.object_key


def test_tampered_existing_object_fails_before_manifest_write() -> None:
    store = MemoryArchiveStore()
    first_writer = RecordingWriter()
    batch = normalize_tpex_monthly_ohlc(_payload())
    result = _service(store, first_writer).archive(batch, backfill_task_id=91)
    stored = store.objects[result.object_key]
    stored.body = bytes([stored.body[0] ^ 1]) + stored.body[1:]
    retry_writer = RecordingWriter()

    with pytest.raises(IngestionError) as captured:
        _service(store, retry_writer).archive(batch, backfill_task_id=91)

    assert captured.value.reason_code == "HISTORICAL_ARCHIVE_CONTENT_MISMATCH"
    assert retry_writer.rows == []
