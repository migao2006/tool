from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from hashlib import sha256
import json

from src.data.providers.contracts import ProviderPayload


RETRIEVED_AT = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)
TPEX_FIELDS = [
    "股票代號",
    "公司名稱",
    "終止上櫃日期",
    "終止上櫃原因",
    "公司資料網址",
]


def provider_payload(
    provider: str,
    payload: object,
    *,
    retrieved_at: datetime = RETRIEVED_AT,
) -> ProviderPayload:
    digest = sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return ProviderPayload(
        provider=provider,
        dataset="delisting_registry",
        source_version="official.v1",
        source_url="https://example.test/delisting-registry",
        retrieved_at=retrieved_at,
        payload_sha256=digest,
        payload=payload,
    )


def twse_payload(
    rows: list[dict[str, object]] | None = None,
    *,
    retrieved_at: datetime = RETRIEVED_AT,
) -> ProviderPayload:
    return provider_payload(
        "TWSE",
        rows
        or [
            {
                "DelistingDate": "115/06/23",
                "Company": "測試上市公司",
                "Code": "6806",
            }
        ],
        retrieved_at=retrieved_at,
    )


def tpex_payload(
    rows: list[list[object]] | None = None,
    *,
    retrieved_at: datetime = RETRIEVED_AT,
    total_count: int | None = None,
    fields: list[str] | None = None,
    stat: str = "ok",
) -> ProviderPayload:
    data = rows or [
        [
            "6747",
            "測試上櫃公司",
            "114-12-04",
            "終止上櫃原因",
            "https://mops.twse.com.tw/mops/",
        ]
    ]
    return provider_payload(
        "TPEX",
        {
            "tables": [
                {
                    "fields": fields or TPEX_FIELDS,
                    "data": data,
                    "totalCount": len(data) if total_count is None else total_count,
                }
            ],
            "date": "ALL",
            "stat": stat,
        },
        retrieved_at=retrieved_at,
    )


def import_payloads() -> dict[str, dict[str, ProviderPayload]]:
    twse_rows = [
        {
            "DelistingDate": "115/06/23",
            "Company": f"上市測試公司{index}",
            "Code": str(1000 + index),
        }
        for index in range(200)
    ]
    tpex_rows = [
        [
            str(2000 + index),
            f"上櫃測試公司{index}",
            "114-12-04",
            "測試原因",
            "https://mops.twse.com.tw/mops/",
        ]
        for index in range(500)
    ]
    return {
        "TWSE": {"delisting_registry": twse_payload(twse_rows)},
        "TPEX": {"delisting_registry": tpex_payload(tpex_rows)},
    }


class FakeProvider:
    def __init__(self, payloads: Mapping[str, ProviderPayload]) -> None:
        self.payloads = dict(payloads)
        self.calls: list[str] = []

    def fetch(self, dataset: str) -> ProviderPayload:
        self.calls.append(dataset)
        return self.payloads[dataset]


class FakeWriter:
    def __init__(self, *, omit_source: str | None = None) -> None:
        self.omit_source = omit_source
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
                "table": table,
                "rows": materialized,
                "on_conflict": on_conflict,
                "select": select,
                "return_rows": return_rows,
                "preserve_existing": preserve_existing,
            }
        )
        if table == "data_sources":
            return [
                {"source_id": index * 10, "source_code": row["source_code"]}
                for index, row in enumerate(materialized, start=1)
                if row["source_code"] in {"TWSE", "TPEX"}
                and row["source_code"] != self.omit_source
            ]
        return []

    def count_rows(self, table: str) -> int:
        self.calls.append({"table": table, "operation": "count"})
        return 123
