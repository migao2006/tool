"""Deterministic FinMind action/state evidence fixtures and test doubles."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from hashlib import sha256
import json

from src.data.ingestion.finmind_historical_evidence_contracts import (
    HistoricalEvidenceIdentity,
)
from src.data.providers.contracts import ProviderPayload


RETRIEVED_AT = datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc)


def payload(
    dataset: str,
    rows: Sequence[Mapping[str, object]],
    *,
    source_url: str = "https://api.finmindtrade.com/api/v4/data",
) -> ProviderPayload:
    body: dict[str, object] = {"status": 200, "data": [dict(row) for row in rows]}
    encoded = json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return ProviderPayload(
        provider="FINMIND",
        dataset=dataset,
        source_version="api.v4",
        source_url=source_url,
        retrieved_at=RETRIEVED_AT,
        payload_sha256=sha256(encoded).hexdigest(),
        payload=body,
    )


def quota_payload(*, used: int = 10, limit: int = 600) -> ProviderPayload:
    body = {"user_count": used, "api_request_limit": limit}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return ProviderPayload(
        provider="FINMIND",
        dataset="api_quota",
        source_version="api.web.v2",
        source_url="https://api.web.finmindtrade.com/v2/user_info",
        retrieved_at=RETRIEVED_AT,
        payload_sha256=sha256(encoded).hexdigest(),
        payload=body,
    )


def evidence_payloads() -> tuple[ProviderPayload, ...]:
    return (
        payload(
            "dividend_results",
            [
                {
                    "date": "2024-06-13",
                    "stock_id": "2330",
                    "before_price": 923,
                    "after_price": 920,
                    "stock_and_cache_dividend": 3,
                    "stock_or_cache_dividend": "息",
                    "max_price": 1010,
                    "min_price": 828,
                    "open_price": 920,
                    "reference_price": 920,
                }
            ],
        ),
        payload(
            "stock_splits",
            [
                {
                    "date": "2020-07-01",
                    "stock_id": "2330",
                    "type": "分割",
                    "before_price": 100,
                    "after_price": 50,
                    "max_price": 55,
                    "min_price": 45,
                    "open_price": 50,
                },
                {
                    "date": "2020-07-01",
                    "stock_id": "0050",
                    "type": "分割",
                    "before_price": 100,
                    "after_price": 50,
                    "max_price": 55,
                    "min_price": 45,
                    "open_price": 50,
                },
            ],
        ),
        payload(
            "par_value_changes",
            [
                {
                    "date": "2021-08-02",
                    "stock_id": "2330",
                    "stock_name": "台積電",
                    "before_close": 100,
                    "after_ref_close": 20,
                    "after_ref_max": 22,
                    "after_ref_min": 18,
                    "after_ref_open": 20,
                }
            ],
        ),
        payload(
            "suspended",
            [
                {
                    "date": "2023-01-10",
                    "stock_id": "2330",
                    "suspension_time": "15:00:00",
                    "resumption_date": "2023-01-12",
                    "resumption_time": "09:00:00",
                }
            ],
        ),
    )


def identity() -> HistoricalEvidenceIdentity:
    return HistoricalEvidenceIdentity(
        listing_evidence_id=11,
        listing_period_id="TWSE:2330:2000-01-01",
        security_id=101,
        source_symbol="2330",
        effective_from=date(2000, 1, 1),
        effective_to=None,
        available_at=datetime(2010, 1, 1, tzinfo=timezone.utc),
    )


def identity_row() -> dict[str, object]:
    item = identity()
    return {
        "listing_evidence_id": item.listing_evidence_id,
        "listing_period_id": item.listing_period_id,
        "security_id": item.security_id,
        "listing_market": item.market,
        "asset_type": item.asset_type,
        "source_symbol": item.source_symbol,
        "effective_from": item.effective_from.isoformat(),
        "effective_to": None,
        "available_at": item.available_at.isoformat(),
    }


class FakeProvider:
    def __init__(self, *, remaining: int = 590) -> None:
        self.remaining = remaining
        self.calls: list[tuple[str, str | None]] = []
        fixtures = evidence_payloads()
        self.by_dataset = {item.dataset: item for item in fixtures}

    def fetch_quota(self) -> ProviderPayload:
        self.calls.append(("api_quota", None))
        return quota_payload(used=600 - self.remaining, limit=600)

    def fetch(
        self,
        dataset: str,
        *,
        data_id: str | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> ProviderPayload:
        _ = (start_date, end_date)
        self.calls.append((dataset, data_id))
        if dataset == "dividend_results" and data_id != "2330":
            return payload(dataset, [])
        return self.by_dataset[dataset]


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
        self.calls.append(
            {
                "operation": "upsert",
                "table": table,
                "rows": [dict(row) for row in rows],
                "on_conflict": on_conflict,
                "select": select,
                "return_rows": return_rows,
                "preserve_existing": preserve_existing,
            }
        )
        if table == "data_sources" and self.return_source:
            return [{"source_id": 42, "source_code": "FINMIND"}]
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
        return [identity_row()]

    def count_rows(self, table: str) -> int:
        self.calls.append({"operation": "count", "table": table})
        return 77
