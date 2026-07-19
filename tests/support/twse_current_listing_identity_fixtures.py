"""Fixtures for current MOPS listing-identity evidence tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import final

from src.data.providers.contracts import ProviderPayload


RETRIEVED_AT = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)


def profile_row(
    symbol: str = "2330",
    *,
    name: str = "台灣積體電路製造股份有限公司",
    listing_date: object = "19940905",
    registration_id: str | None = "22099131",
) -> dict[str, object]:
    row: dict[str, object] = {
        "公司代號": symbol,
        "公司名稱": name,
        "公司簡稱": "測試公司",
        "上市日期": listing_date,
    }
    if registration_id is not None:
        row["營利事業統一編號"] = registration_id
    return row


def profile_rows(count: int = 500) -> list[dict[str, object]]:
    return [
        profile_row(
            str(1000 + index),
            name=f"上市測試公司{index}",
            listing_date="1000101",
            registration_id=f"{10_000_000 + index:08d}",
        )
        for index in range(count)
    ]


def mops_payload(
    rows: list[dict[str, object]] | None = None,
    *,
    retrieved_at: datetime = RETRIEVED_AT,
    provider: str = "MOPS",
    dataset: str = "listed_company_profile",
) -> ProviderPayload:
    body = rows if rows is not None else [profile_row()]
    payload_hash = sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return ProviderPayload(
        provider=provider,
        dataset=dataset,
        source_version="exchange-openapi.v1",
        source_url="https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
        retrieved_at=retrieved_at,
        payload_sha256=payload_hash,
        payload=body,
    )


@final
class FakeProvider:
    def __init__(self, payload: ProviderPayload) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def fetch(self, dataset: str) -> ProviderPayload:
        self.calls.append(dataset)
        return self.payload


@final
class FakeWriter:
    def __init__(self, *, return_source: bool = True) -> None:
        self.return_source = return_source
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
        materialized = [dict(row) for row in rows]
        self.calls.append(
            {
                "operation": "upsert",
                "table": table,
                "rows": materialized,
                "on_conflict": on_conflict,
                "select": select,
                "return_rows": return_rows,
                "preserve_existing": preserve_existing,
            }
        )
        if table == "data_sources" and self.return_source:
            return [{"source_id": 42, "source_code": "MOPS"}]
        return []

    def count_rows(self, table: str) -> int:
        self.calls.append({"operation": "count", "table": table})
        return 500
