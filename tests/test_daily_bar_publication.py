from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
from hashlib import sha256
import json

from src.data.ingestion.daily_bar_publication import (
    DAILY_BAR_PUBLICATION_CONTENT_TYPE,
    DailyBarPublicationService,
    DailyBarPublicationSourceRow,
    DailyBarPublicationSourceSnapshot,
)
from src.data.object_storage.r2_client import ObjectMetadata
from src.data.research.daily_bar_publication_snapshot import (
    DailyBarPublicationManifest,
    DailyBarPublicationSnapshotReader,
)


TRADING_DATE = date(2026, 7, 20)
AVAILABLE_AT = datetime(2026, 7, 21, 14, 23, tzinfo=timezone.utc)


def _rows() -> tuple[DailyBarPublicationSourceRow, ...]:
    return tuple(
        DailyBarPublicationSourceRow(
            daily_bar_id=index + 1,
            security_id=index + 1,
            symbol=f"{1000 + index:04d}",
            market="TWSE",
            trade_date=TRADING_DATE,
            open_price=100.0 + index,
            high_price=102.0 + index,
            low_price=99.0 + index,
            close_price=101.0 + index,
            trading_volume=1_000_000.0 + index,
            trading_value=(101.0 + index) * (1_000_000.0 + index),
            trade_count=1_000 + index,
            source_id=7,
            source_version="official-openapi.v1",
            available_at=AVAILABLE_AT,
        )
        for index in range(500)
    )


def _snapshot() -> DailyBarPublicationSourceSnapshot:
    rows = _rows()
    content_hash = sha256(
        json.dumps(
            [row.canonical_mapping() for row in rows],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return DailyBarPublicationSourceSnapshot(
        market="TWSE",
        trading_date=TRADING_DATE,
        rows=rows,
        source_id=7,
        source_url="https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
        source_versions=("official-openapi.v1",),
        first_observed_at=AVAILABLE_AT,
        normalized_content_sha256=content_hash,
    )


class MemoryStore:
    bucket_name = "alpha-lens-market-archive"

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str, dict[str, str]]] = {}

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
        self.objects[key] = (body, content_type, dict(metadata or {}))
        return True

    def head(self, key: str) -> ObjectMetadata | None:
        value = self.objects.get(key)
        if value is None:
            return None
        body, content_type, metadata = value
        return ObjectMetadata(
            key=key,
            content_length=len(body),
            etag='"daily-publication"',
            content_type=content_type,
            metadata=metadata,
        )

    def get(self, key: str) -> bytes:
        return self.objects[key][0]


class MemoryManifestRepository:
    def __init__(self) -> None:
        self.saved: dict[str, object] | None = None

    def save_and_read(self, manifest: Mapping[str, object]) -> dict[str, object]:
        self.saved = {"publication_snapshot_id": 41, **dict(manifest)}
        return dict(self.saved)


def test_publication_round_trip_is_immutable_and_reproducible() -> None:
    store = MemoryStore()
    repository = MemoryManifestRepository()

    result = DailyBarPublicationService(  # type: ignore[arg-type]
        store=store,
        repository=repository,
    ).publish(_snapshot())

    assert result.created
    assert result.row_count == 500
    assert result.trading_date == TRADING_DATE
    assert repository.saved is not None
    manifest = DailyBarPublicationManifest.from_mapping(repository.saved)
    read_back = DailyBarPublicationSnapshotReader(store).read(manifest)  # type: ignore[arg-type]

    assert len(read_back.rows) == 500
    assert read_back.rows[0].trade_date == TRADING_DATE
    assert read_back.manifest.normalized_content_sha256 == (_snapshot().normalized_content_sha256)
    stored = store.objects[result.object_key]
    assert stored[1] == DAILY_BAR_PUBLICATION_CONTENT_TYPE
    assert stored[2]["parquet-sha256"] == result.parquet_sha256
    assert stored[2]["trading-date"] == TRADING_DATE.isoformat()
