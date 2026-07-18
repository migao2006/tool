"""Fixtures for current TWSE and TPEx corporate-action announcements."""

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
        source_url="https://example.test/corporate-actions",
        retrieved_at=retrieved_at,
        payload_sha256=digest,
        payload=rows,
    )


def twse_payload(rows: list[dict[str, object]] | None = None) -> ProviderPayload:
    return provider_payload(
        "TWSE",
        "ex_rights",
        rows
        or [
            {
                "Code": "2330",
                "Date": "1150720",
                "CashDividend": "2.5",
                "StockDividendRatio": "0.1",
                "SubscriptionRatio": "0",
                "Exdividend": "\u9664\u606f",
            }
        ],
    )


def tpex_forecast_payload(
    rows: list[dict[str, object]] | None = None,
) -> ProviderPayload:
    return provider_payload(
        "TPEX",
        "ex_rights_forecast",
        rows
        or [
            {
                "SecuritiesCompanyCode": "6488",
                "ExRrightsExDividendDate": "20260721",
                "CashDividend": "",
                "StockDividendRatio": "0.05",
                "SubscriptionRatioToNewSharesIssued": "0.02",
                "ExRrightsExDividend": "\u9664\u6b0a\u9664\u606f",
            }
        ],
    )


def security_ids() -> dict[tuple[str, str], int]:
    return {("TWSE", "2330"): 101, ("TWSE", "2317"): 102, ("TPEX", "6488"): 201}


def import_payloads(profile_count: int = 500) -> dict[str, dict[str, ProviderPayload]]:
    """Return enough official-profile identities to pass the import coverage gate."""

    listed_symbols = ["2330", *[str(code) for code in range(2000, 3000) if code != 2330]]
    otc_symbols = ["6488", *[str(code) for code in range(3000, 4000)]]
    listed = [
        {
            "公司代號": symbol,
            "公司簡稱": f"上市{symbol}",
            "上市日期": "1000101",
        }
        for symbol in listed_symbols[:profile_count]
    ]
    otc = [
        {
            "SecuritiesCompanyCode": symbol,
            "CompanyAbbreviation": f"上櫃{symbol}",
            "DateOfListing": "20110101",
        }
        for symbol in otc_symbols[:profile_count]
    ]
    return {
        "MOPS": {
            "listed_company_profile": provider_payload(
                "MOPS", "listed_company_profile", listed
            ),
            "otc_company_profile": provider_payload("MOPS", "otc_company_profile", otc),
        },
        "TWSE": {"ex_rights": twse_payload()},
        "TPEX": {"ex_rights_forecast": tpex_forecast_payload()},
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
        omit_security: tuple[str, str] | None = None,
    ) -> None:
        self.omit_source = omit_source
        self.omit_security = omit_security
        self.calls: list[dict[str, object]] = []
        self.refresh_calls = 0

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
                if row["source_code"] != self.omit_source
            ]
        if table == "securities":
            return [
                {
                    "security_id": index * 100,
                    "market": row["market"],
                    "symbol": row["symbol"],
                }
                for index, row in enumerate(materialized, start=1)
                if (row["market"], row["symbol"]) != self.omit_security
            ]
        return []

    def count_rows(self, table: str) -> int:
        self.calls.append({"operation": "count", "table": table})
        return 123

    def refresh_home_data_status(self) -> None:
        self.refresh_calls += 1
