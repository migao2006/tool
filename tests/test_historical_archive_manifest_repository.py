from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256

import pytest

from src.data.archive.contracts import HistoricalArchiveReadError
from src.data.archive.manifest_repository import HistoricalArchiveManifestRepository


def _manifest(archive_id: int) -> dict[str, object]:
    object_key = f"history/{archive_id}.parquet"
    bucket = "alpha-lens-archive"
    return {
        "archive_id": archive_id,
        "archive_key": sha256(f"{bucket}\0{object_key}".encode()).hexdigest(),
        "storage_provider": "CLOUDFLARE_R2",
        "bucket_name": bucket,
        "object_key": object_key,
        "object_etag": f'"etag-{archive_id}"',
        "schema_version": "historical_daily_bars.v1",
        "provider_code": "FINMIND",
        "source_dataset": "daily_bars",
        "source_version": "v1",
        "source_symbol": f"{archive_id:04d}",
        "scheduled_market": "TWSE",
        "asset_type": "COMMON_STOCK",
        "requested_start_date": "2021-07-19",
        "requested_end_date": "2026-07-17",
        "min_trade_date": "2021-07-19",
        "max_trade_date": "2026-07-17",
        "source_payload_hash": "a" * 64,
        "parquet_sha256": "b" * 64,
        "byte_size": 100,
        "row_count": 10,
        "parsed_row_count": 9,
        "quarantined_row_count": 1,
        "first_observed_at": datetime(2026, 7, 19, tzinfo=timezone.utc).isoformat(),
        "point_in_time_status": "UNVERIFIED",
        "usage_scope": "RAW_LANDING_ONLY",
        "system_status": "RESEARCH_ONLY",
        "reason_codes": ["HISTORICAL_POINT_IN_TIME_UNVERIFIED"],
    }


class FakeSource:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[Mapping[str, str], int]] = []

    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]:
        assert table == "historical_archive_objects"
        assert "parquet_sha256" in select
        normalized = dict(filters or {})
        self.calls.append((normalized, limit))
        cursor = int(normalized["archive_id"].removeprefix("gt."))
        return [row for row in self.rows if int(row["archive_id"]) > cursor][:limit]


def test_repository_keyset_pages_and_builds_deterministic_snapshot() -> None:
    source = FakeSource([_manifest(1), _manifest(2), _manifest(3)])
    repository = HistoricalArchiveManifestRepository(source, page_size=2)

    first = repository.fetch()
    second = repository.fetch()

    assert first.object_count == 3
    assert first.complete is True
    assert first.snapshot_sha256 == second.snapshot_sha256
    assert [row["archive_id"] for row in first.rows] == [1, 2, 3]
    assert source.calls[:2] == [
        ({"archive_id": "gt.0", "order": "archive_id.asc"}, 2),
        ({"archive_id": "gt.2", "order": "archive_id.asc"}, 2),
    ]


def test_repository_marks_limited_sample_and_rejects_invalid_manifest() -> None:
    source = FakeSource([_manifest(1), _manifest(2)])
    limited = HistoricalArchiveManifestRepository(source).fetch(max_objects=1)

    assert limited.object_count == 1
    assert limited.complete is False

    invalid = _manifest(1)
    invalid["parquet_sha256"] = "invalid"
    with pytest.raises(
        HistoricalArchiveReadError,
        match="incomplete or inconsistent",
    ):
        HistoricalArchiveManifestRepository(FakeSource([invalid])).fetch()


def test_repository_rejects_non_increasing_archive_ids() -> None:
    source = FakeSource([_manifest(2), _manifest(1)])

    with pytest.raises(
        HistoricalArchiveReadError,
        match="strictly ordered",
    ):
        HistoricalArchiveManifestRepository(source).fetch()
