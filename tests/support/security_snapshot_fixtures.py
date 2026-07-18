from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json

from src.data.ingestion.security_snapshot_contracts import MarketSnapshotPayloads
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
        source_url="https://example.test/source",
        retrieved_at=retrieved_at,
        payload_sha256=digest,
        payload=rows,
    )


def twse_bundle(
    *,
    profiles: list[dict[str, object]],
    restrictions: list[dict[str, object]] | None = None,
    suspended: list[dict[str, object]] | None = None,
    attention: list[dict[str, object]] | None = None,
    disposals: list[dict[str, object]] | None = None,
) -> MarketSnapshotPayloads:
    return MarketSnapshotPayloads(
        profile=provider_payload("MOPS", "listed_company_profile", profiles),
        restrictions=provider_payload(
            "TWSE", "changed_trading", restrictions or []
        ),
        suspended=provider_payload("TWSE", "suspended", suspended or []),
        attention=provider_payload("TWSE", "attention", attention or []),
        disposals=provider_payload("TWSE", "disposals", disposals or []),
    )


def tpex_bundle(
    *,
    profiles: list[dict[str, object]],
    restrictions: list[dict[str, object]] | None = None,
    suspended: list[dict[str, object]] | None = None,
    attention: list[dict[str, object]] | None = None,
    disposals: list[dict[str, object]] | None = None,
) -> MarketSnapshotPayloads:
    return MarketSnapshotPayloads(
        profile=provider_payload("MOPS", "otc_company_profile", profiles),
        restrictions=provider_payload(
            "TPEX", "trading_restrictions", restrictions or []
        ),
        suspended=provider_payload("TPEX", "suspended_history", suspended or []),
        attention=provider_payload("TPEX", "attention", attention or []),
        disposals=provider_payload("TPEX", "disposals", disposals or []),
    )


def import_payloads(
    profile_count: int = 500,
    *,
    listed_profile_date: str = "1150718",
) -> dict[str, dict[str, ProviderPayload]]:
    listed = [
        {
            "出表日期": listed_profile_date,
            "公司代號": str(2000 + index),
            "公司簡稱": f"上市{index}",
            "產業別": "24",
            "上市日期": "1000101",
        }
        for index in range(profile_count)
    ]
    otc = [
        {
            "Date": "20260718",
            "SecuritiesCompanyCode": str(3000 + index),
            "CompanyAbbreviation": f"上櫃{index}",
            "SecuritiesIndustryCode": "24",
            "DateOfListing": "20110101",
        }
        for index in range(profile_count)
    ]
    return {
        "MOPS": {
            "listed_company_profile": provider_payload(
                "MOPS", "listed_company_profile", listed
            ),
            "otc_company_profile": provider_payload(
                "MOPS", "otc_company_profile", otc
            ),
        },
        "TWSE": {
            "changed_trading": provider_payload("TWSE", "changed_trading", []),
            "suspended": provider_payload("TWSE", "suspended", []),
            "attention": provider_payload("TWSE", "attention", []),
            "disposals": provider_payload("TWSE", "disposals", []),
        },
        "TPEX": {
            "trading_restrictions": provider_payload(
                "TPEX", "trading_restrictions", []
            ),
            "suspended_history": provider_payload(
                "TPEX", "suspended_history", []
            ),
            "attention": provider_payload("TPEX", "attention", []),
            "disposals": provider_payload("TPEX", "disposals", []),
        },
    }
