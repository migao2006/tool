from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
from typing import final

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


@final
class FakeSource:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows: list[dict[str, object]] = rows
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
        assert select == "archive_id" or "parquet_sha256" in select
        normalized = dict(filters or {})
        self.calls.append((normalized, limit))
        cursor = int(normalized.get("archive_id", "gt.0").removeprefix("gt."))
        selected: list[dict[str, object]] = []
        for row in self.rows:
            archive_id = row.get("archive_id")
            assert isinstance(archive_id, int) and not isinstance(archive_id, bool)
            if archive_id > cursor:
                selected.append(row)
        if normalized.get("order") == "archive_id.desc":
            selected.sort(key=lambda row: int(str(row["archive_id"])), reverse=True)
        return selected[:limit]


def test_repository_keyset_pages_and_builds_deterministic_snapshot() -> None:
    source = FakeSource([_manifest(1), _manifest(2), _manifest(3)])
    repository = HistoricalArchiveManifestRepository(source, page_size=2)

    first = repository.fetch()
    second = repository.fetch()

    assert first.object_count == 3
    assert first.complete is True
    assert first.snapshot_sha256 == second.snapshot_sha256
    assert [row["archive_id"] for row in first.rows] == [1, 2, 3]
    assert first.high_water_archive_id == 3
    assert source.calls[:3] == [
        ({"order": "archive_id.desc"}, 1),
        ({"archive_id": "gt.0", "order": "archive_id.asc"}, 2),
        ({"archive_id": "gt.2", "order": "archive_id.asc"}, 2),
    ]


def test_repository_freezes_high_water_before_keyset_scan() -> None:
    class AppendingSource(FakeSource):
        appended = False

        def select_rows(self, *args, **kwargs):
            page = super().select_rows(*args, **kwargs)
            filters = dict(kwargs.get("filters") or {})
            if filters.get("order") == "archive_id.asc" and not self.appended:
                self.rows.append(_manifest(4))
                self.appended = True
            return page

    source = AppendingSource([_manifest(1), _manifest(2), _manifest(3)])
    snapshot = HistoricalArchiveManifestRepository(source, page_size=2).fetch()

    assert snapshot.high_water_archive_id == 3
    assert snapshot.complete is True
    assert [row["archive_id"] for row in snapshot.rows] == [1, 2, 3]


def test_repository_stops_at_explicit_high_water_gap_without_repeating_page() -> None:
    source = FakeSource([_manifest(1), _manifest(3), _manifest(4)])

    snapshot = HistoricalArchiveManifestRepository(source, page_size=2).fetch(
        through_archive_id=2
    )

    assert snapshot.high_water_archive_id == 2
    assert snapshot.complete is True
    assert [row["archive_id"] for row in snapshot.rows] == [1]
    assert source.calls == [({"archive_id": "gt.0", "order": "archive_id.asc"}, 2)]


def test_snapshot_hash_covers_all_meaning_bearing_manifest_fields() -> None:
    original = _manifest(1)
    revised_source = dict(original)
    revised_source["source_version"] = "v2"
    revised_reason = dict(original)
    revised_reason["reason_codes"] = [
        "HISTORICAL_POINT_IN_TIME_UNVERIFIED",
        "SOURCE_POLICY_CHANGED",
    ]

    original_hash = (
        HistoricalArchiveManifestRepository(FakeSource([original]))
        .fetch()
        .snapshot_sha256
    )
    revised_source_hash = (
        HistoricalArchiveManifestRepository(FakeSource([revised_source]))
        .fetch()
        .snapshot_sha256
    )
    revised_reason_hash = (
        HistoricalArchiveManifestRepository(FakeSource([revised_reason]))
        .fetch()
        .snapshot_sha256
    )

    assert len({original_hash, revised_source_hash, revised_reason_hash}) == 3


def test_snapshot_rows_and_hash_share_the_same_normalized_values() -> None:
    original = _manifest(1)
    padded = dict(original)
    padded["source_symbol"] = f"  {original['source_symbol']}  "
    padded["source_version"] = "  v1  "

    clean_snapshot = HistoricalArchiveManifestRepository(FakeSource([original])).fetch()
    padded_snapshot = HistoricalArchiveManifestRepository(FakeSource([padded])).fetch()

    assert padded_snapshot.rows[0]["source_symbol"] == original["source_symbol"]
    assert padded_snapshot.rows[0]["source_version"] == "v1"
    assert padded_snapshot.snapshot_sha256 == clean_snapshot.snapshot_sha256


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
        _ = HistoricalArchiveManifestRepository(FakeSource([invalid])).fetch()


def test_repository_rejects_non_increasing_archive_ids() -> None:
    source = FakeSource([_manifest(2), _manifest(1)])

    with pytest.raises(
        HistoricalArchiveReadError,
        match="strictly ordered",
    ):
        _ = HistoricalArchiveManifestRepository(source).fetch()


def test_repository_applies_scope_filters_to_every_keyset_page() -> None:
    source = FakeSource([_manifest(1), _manifest(2), _manifest(3)])
    filters = {
        "source_dataset": "eq.daily_bars",
        "scheduled_market": "eq.TWSE",
        "asset_type": "eq.COMMON_STOCK",
    }

    snapshot = HistoricalArchiveManifestRepository(source, page_size=2).fetch(
        filters=filters
    )

    assert snapshot.object_count == 3
    assert all(set(filters.items()).issubset(call[0].items()) for call in source.calls)
    with pytest.raises(ValueError, match="cannot override"):
        _ = HistoricalArchiveManifestRepository(source).fetch(
            filters={"archive_id": "gt.100"}
        )
