from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime, timezone
from hashlib import sha256
import json

import pytest

from src.data.daily_bar_publication_contracts import (
    DAILY_BAR_PUBLICATION_CONTENT_TYPE as CONTRACT_CONTENT_TYPE,
    DAILY_BAR_PUBLICATION_SCHEMA_VERSION as CONTRACT_SCHEMA_VERSION,
    DailyBarPublicationSourceRow as ContractSourceRow,
    DailyBarPublicationSourceSnapshot as ContractSourceSnapshot,
)
from src.data.ingestion.daily_bar_publication import (
    DAILY_BAR_PUBLICATION_CONTENT_TYPE,
    DAILY_BAR_PUBLICATION_SCHEMA_VERSION,
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


def test_source_contract_imports_are_compatible() -> None:
    assert DAILY_BAR_PUBLICATION_SCHEMA_VERSION == "daily-bar-publication.v1"
    assert DAILY_BAR_PUBLICATION_SCHEMA_VERSION == CONTRACT_SCHEMA_VERSION
    assert DAILY_BAR_PUBLICATION_CONTENT_TYPE == "application/vnd.apache.parquet"
    assert DAILY_BAR_PUBLICATION_CONTENT_TYPE == CONTRACT_CONTENT_TYPE
    assert DailyBarPublicationSourceRow is ContractSourceRow
    assert DailyBarPublicationSourceSnapshot is ContractSourceSnapshot


def test_source_row_preserves_fields_equality_and_mappings() -> None:
    row = _rows()[0]
    expected_canonical: dict[str, object] = {
        "daily_bar_id": 1,
        "security_id": 1,
        "symbol": "1000",
        "market": "TWSE",
        "asset_type": "COMMON_STOCK",
        "trade_date": "2026-07-20",
        "open_price": 100.0,
        "high_price": 102.0,
        "low_price": 99.0,
        "close_price": 101.0,
        "trading_volume": 1_000_000.0,
        "trading_value": 101_000_000.0,
        "trade_count": 1_000,
        "source_id": 7,
        "source_version": "official-openapi.v1",
        "available_at": "2026-07-21T14:23:00+00:00",
    }

    assert row == replace(row)
    assert row.canonical_mapping() == expected_canonical
    assert row.parquet_mapping() == {
        **expected_canonical,
        "trade_date": TRADING_DATE,
        "available_at": AVAILABLE_AT,
    }
    assert row.canonical_mapping() == expected_canonical


def test_source_snapshot_preserves_fields_and_equality() -> None:
    snapshot = _snapshot()

    assert snapshot == replace(snapshot)
    assert snapshot.market == "TWSE"
    assert snapshot.trading_date == TRADING_DATE
    assert len(snapshot.rows) == 500
    assert snapshot.source_id == 7
    assert snapshot.source_versions == ("official-openapi.v1",)
    assert snapshot.first_observed_at == AVAILABLE_AT
    assert len(snapshot.normalized_content_sha256) == 64


def test_source_row_rejects_timezone_naive_available_at_with_stable_error() -> None:
    with pytest.raises(ValueError) as captured:
        replace(_rows()[0], available_at=AVAILABLE_AT.replace(tzinfo=None))

    assert type(captured.value) is ValueError
    assert str(captured.value) == (
        "daily-bar publication available_at must be timezone-aware"
    )


def test_source_row_rejects_non_finite_numeric_value_with_stable_error() -> None:
    with pytest.raises(ValueError) as captured:
        replace(_rows()[0], close_price=float("nan"))

    assert type(captured.value) is ValueError
    assert str(captured.value) == "daily-bar publication numeric value is not finite"


def test_source_snapshot_rejects_insufficient_market_coverage() -> None:
    snapshot = _snapshot()

    with pytest.raises(ValueError) as captured:
        replace(snapshot, rows=snapshot.rows[:-1])

    assert type(captured.value) is ValueError
    assert str(captured.value) == "daily-bar publication snapshot coverage is too low"


def test_source_snapshot_rejects_duplicate_security() -> None:
    snapshot = _snapshot()
    duplicate = replace(
        snapshot.rows[-1],
        security_id=snapshot.rows[0].security_id,
    )

    with pytest.raises(ValueError) as captured:
        replace(snapshot, rows=(*snapshot.rows[:-1], duplicate))

    assert type(captured.value) is ValueError
    assert str(captured.value) == (
        "daily-bar publication snapshot contains duplicate securities"
    )


def test_source_snapshot_rejects_mixed_market() -> None:
    snapshot = _snapshot()
    other_market = replace(snapshot.rows[-1], market="TPEX")

    with pytest.raises(ValueError) as captured:
        replace(snapshot, rows=(*snapshot.rows[:-1], other_market))

    assert type(captured.value) is ValueError
    assert str(captured.value) == "daily-bar publication snapshot contains mixed scope"


def test_source_snapshot_rejects_invalid_sha256() -> None:
    with pytest.raises(ValueError) as captured:
        replace(_snapshot(), normalized_content_sha256="not-a-sha256")

    assert type(captured.value) is ValueError
    assert str(captured.value) == "daily-bar publication content hash is invalid"


def test_publication_round_trip_is_immutable_and_reproducible() -> None:
    store = MemoryStore()
    repository = MemoryManifestRepository()

    result = DailyBarPublicationService(
        store=store,  # type: ignore[arg-type]
        repository=repository,  # type: ignore[arg-type]
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
