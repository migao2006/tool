"""Fixtures for official current-month total-return benchmark observations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from hashlib import sha256
import json

from src.data.providers.contracts import ProviderPayload


RETRIEVED_AT = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)


def provider_payload(
    provider: str,
    dataset: str,
    rows: list[dict[str, object]],
    *,
    retrieved_at: datetime = RETRIEVED_AT,
) -> ProviderPayload:
    digest = sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return ProviderPayload(
        provider=provider,
        dataset=dataset,
        source_version="openapi.v1",
        source_url="https://example.test/total-return-index",
        retrieved_at=retrieved_at,
        payload_sha256=digest,
        payload=rows,
    )


def twse_return_index_payload(
    rows: list[dict[str, object]] | None = None,
) -> ProviderPayload:
    return provider_payload(
        "TWSE",
        "return_index",
        rows
        or [
            {"Date": "1150716", "TAIEXTotalReturnIndex": "53,210.45"},
            {"Date": "1150717", "TAIEXTotalReturnIndex": "53,441.21"},
        ],
    )


def tpex_return_index_payload(
    rows: list[dict[str, object]] | None = None,
) -> ProviderPayload:
    return provider_payload(
        "TPEX",
        "return_index",
        rows
        or [
            {"Date": "1150716", "TPExTotalReturnIndex": "412.34"},
            {"Date": "1150717", "TPExTotalReturnIndex": "414.56"},
        ],
    )


def import_payloads() -> dict[str, dict[str, ProviderPayload]]:
    return {
        "TWSE": {"return_index": twse_return_index_payload()},
        "TPEX": {"return_index": tpex_return_index_payload()},
    }


class FakeProvider:
    def __init__(self, payloads: Mapping[str, ProviderPayload]) -> None:
        self.payloads = dict(payloads)
        self.calls: list[str] = []

    def fetch(self, dataset: str) -> ProviderPayload:
        self.calls.append(dataset)
        return self.payloads[dataset]


class FakeWriter:
    def __init__(
        self,
        *,
        omit_source: str | None = None,
        omit_definition: str | None = None,
    ) -> None:
        self.omit_source = omit_source
        self.omit_definition = omit_definition
        self.calls: list[dict[str, object]] = []
        self.definition_rows: list[dict[str, object]] = []

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
        if table == "data_sources":
            return [
                {"source_id": index * 10, "source_code": row["source_code"]}
                for index, row in enumerate(materialized, start=1)
                if row["source_code"] in {"TWSE", "TPEX"}
                and row["source_code"] != self.omit_source
            ]
        if table == "benchmark_definitions":
            self.definition_rows = [
                {
                    "benchmark_id": index * 100,
                    "benchmark_code": row["benchmark_code"],
                    "benchmark_version": row["benchmark_version"],
                }
                for index, row in enumerate(materialized, start=1)
                if row["benchmark_code"] != self.omit_definition
            ]
            return self.definition_rows
        return []

    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]:
        self.calls.append(
            {
                "operation": "select",
                "table": table,
                "select": select,
                "filters": dict(filters or {}),
                "limit": limit,
            }
        )
        return self.definition_rows[:limit]

    def count_rows(self, table: str) -> int:
        self.calls.append({"operation": "count", "table": table})
        return 123
