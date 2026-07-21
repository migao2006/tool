from __future__ import annotations

from collections.abc import Mapping
from typing import final

from src.data.research.twse_current_identity_repository import (
    TwseCurrentIdentityRepository,
)


@final
class FakeSecuritySource:
    def __init__(self) -> None:
        self.calls: list[Mapping[str, str]] = []
        self.rows = [
            {
                "security_id": 1,
                "symbol": "1101",
                "market": "TWSE",
                "asset_type": "COMMON_STOCK",
                "listing_date": "1962-02-09",
                "delisting_date": None,
            },
            {
                "security_id": 2,
                "symbol": "2330",
                "market": "TWSE",
                "asset_type": "COMMON_STOCK",
                "listing_date": None,
                "delisting_date": None,
            },
        ]

    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]:
        assert table == "securities"
        assert "listing_date" in select
        normalized = dict(filters or {})
        self.calls.append(normalized)
        cursor = int(normalized["security_id"].removeprefix("gt."))
        return [row for row in self.rows if int(row["security_id"]) > cursor][:limit]


def test_current_identity_repository_is_scoped_paginated_and_hashed() -> None:
    source = FakeSecuritySource()

    first = TwseCurrentIdentityRepository(source, page_size=1).fetch()
    second = TwseCurrentIdentityRepository(source, page_size=1).fetch()

    assert tuple(first.by_symbol) == ("1101", "2330")
    assert first.by_symbol["1101"].listing_period_id.startswith("CURRENT:TWSE:1101")
    assert first.by_symbol["2330"].listing_date is None
    assert first.snapshot_sha256 == second.snapshot_sha256
    assert all(call["market"] == "eq.TWSE" for call in source.calls)
    assert all(call["asset_type"] == "eq.COMMON_STOCK" for call in source.calls)
    assert [call["security_id"] for call in source.calls[:3]] == [
        "gt.0",
        "gt.1",
        "gt.2",
    ]
