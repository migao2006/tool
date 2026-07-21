from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import final

import pytest

from src.data.canonical import (
    ListingPeriodEvidenceRepository,
    PointInTimeEvidenceReadError,
)


CUTOFF = datetime(2026, 7, 19, tzinfo=timezone.utc)


def _row(row_id: int, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "listing_evidence_id": row_id,
        "listing_period_id": f"period-{row_id}",
        "security_id": 1000 + row_id,
        "listing_market": "TWSE",
        "asset_type": "COMMON_STOCK",
        "isin": f"TW{1000 + row_id:08d}AA",
        "source_symbol": f"{1000 + row_id}",
        "effective_from": "2020-01-01",
        "effective_to": None,
        "identity_resolution_status": "VERIFIED",
        "source_id": 1,
        "source_dataset": "listing_history",
        "source_version": "v1",
        "source_revision_hash": f"{row_id:064x}",
        "source_payload_hash": "f" * 64,
        "first_observed_at": "2025-01-01T00:00:00+00:00",
        "available_at": "2025-01-01T00:00:00+00:00",
        "available_at_basis": "VERSIONED_SNAPSHOT",
        "usage_scope": "POINT_IN_TIME_IDENTITY",
        "system_status": "PASS",
        "reason_codes": [],
    }
    values.update(overrides)
    return values


@final
class FakeSource:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows: list[dict[str, object]] = rows
        self.calls: list[tuple[str, str, Mapping[str, str] | None, int]] = []

    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]:
        self.calls.append((table, select, filters, limit))
        assert filters is not None
        after = int(str(filters["listing_evidence_id"]).split(".", 1)[1])
        result: list[dict[str, object]] = []
        for row in self.rows:
            row_id = row["listing_evidence_id"]
            assert isinstance(row_id, int)
            if row_id > after:
                result.append(row)
        return result[:limit]


def test_repository_keyset_pages_and_builds_deterministic_snapshot() -> None:
    source = FakeSource([_row(1), _row(2), _row(3)])
    repository = ListingPeriodEvidenceRepository(source, page_size=2)

    first = repository.fetch(decision_at=CUTOFF, market="TWSE")
    second = repository.fetch(decision_at=CUTOFF, market="TWSE")

    assert [item.listing_period_id for item in first.identities] == [
        "period-1",
        "period-2",
        "period-3",
    ]
    assert first.snapshot_sha256 == second.snapshot_sha256
    assert first.complete is True
    filters = source.calls[0][2]
    assert filters is not None
    assert filters["available_at"].startswith("lte.")
    assert filters["listing_market"] == "eq.TWSE"


def test_repository_preserves_conflict_evidence_for_fail_closed_resolution() -> None:
    source = FakeSource(
        [
            _row(
                1,
                security_id=None,
                identity_resolution_status="CONFLICT",
                usage_scope="IDENTITY_RESEARCH_ONLY",
                system_status="FAIL",
                reason_codes=["SOURCE_CONTRADICTION"],
            )
        ]
    )

    snapshot = ListingPeriodEvidenceRepository(source).fetch(decision_at=CUTOFF)

    assert snapshot.identities[0].resolution_status == "CONFLICT"
    assert snapshot.identities[0].security_id is None
    assert snapshot.identities[0].reason_codes == ("SOURCE_CONTRADICTION",)


def test_repository_rejects_future_or_malformed_rows_even_if_source_misfilters() -> (
    None
):
    future = FakeSource([_row(1, available_at="2027-01-01T00:00:00+00:00")])
    malformed = FakeSource([_row(1, source_revision_hash="not-a-hash")])

    with pytest.raises(PointInTimeEvidenceReadError) as future_error:
        _ = ListingPeriodEvidenceRepository(future).fetch(decision_at=CUTOFF)
    with pytest.raises(PointInTimeEvidenceReadError) as malformed_error:
        _ = ListingPeriodEvidenceRepository(malformed).fetch(decision_at=CUTOFF)

    assert future_error.value.reason_code == "LISTING_EVIDENCE_FUTURE_ROW"
    assert malformed_error.value.reason_code == "LISTING_EVIDENCE_INVALID"


def test_repository_limit_is_explicitly_marked_incomplete() -> None:
    source = FakeSource([_row(1), _row(2)])

    snapshot = ListingPeriodEvidenceRepository(source).fetch(
        decision_at=CUTOFF, max_rows=1
    )

    assert len(snapshot.identities) == 1
    assert snapshot.complete is False
