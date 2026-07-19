"""Normalize current MOPS profiles as unresolved listing evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from hashlib import sha256
import json
import re
from typing import cast

from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError
from .normalizers import revision_version
from .roc_date import parse_optional_exchange_date
from .twse_current_listing_identity_contracts import (
    NormalizedTwseCurrentListingIdentities,
    TWSE_CURRENT_LISTING_IDENTITY_REASON_CODES,
)


COMMON_STOCK_SYMBOL = re.compile(r"^[0-9]{4}$")
EXPECTED_SOURCE = ("MOPS", "listed_company_profile")
REGISTRATION_ID_FIELDS = ("營利事業統一編號", "統一編號")


def _records(payload: ProviderPayload) -> list[Mapping[str, object]]:
    raw = cast(object, payload.payload)
    if not isinstance(raw, list):
        raise IngestionError(
            "CURRENT_LISTING_IDENTITY_PAYLOAD_INVALID",
            "MOPS listed-company profiles must be an array of objects",
        )
    items = cast(list[object], raw)
    if not all(isinstance(row, Mapping) for row in items):
        raise IngestionError(
            "CURRENT_LISTING_IDENTITY_PAYLOAD_INVALID",
            "MOPS listed-company profiles must be an array of objects",
        )
    return [cast(Mapping[str, object], row) for row in items]


def _row_hash(payload: ProviderPayload, row: Mapping[str, object]) -> str:
    encoded = json.dumps(
        {
            "provider": payload.provider,
            "dataset": payload.dataset,
            "source_row": dict(row),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _registration_id(row: Mapping[str, object]) -> str | None:
    for field in REGISTRATION_ID_FIELDS:
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return None


def normalize_twse_current_listing_identities(
    payload: ProviderPayload,
    *,
    source_id: int,
) -> NormalizedTwseCurrentListingIdentities:
    """Return append-only research evidence without linking a security ID."""

    if source_id <= 0:
        raise ValueError("source_id must be positive")
    if (payload.provider, payload.dataset) != EXPECTED_SOURCE:
        raise IngestionError(
            "CURRENT_LISTING_IDENTITY_SOURCE_INVALID",
            "Current TWSE listing evidence must use the MOPS company profile",
        )

    observed_at = payload.retrieved_at.isoformat()
    source_version = revision_version(payload)
    normalized: dict[str, dict[str, object]] = {}
    excluded = 0
    registration_id_rows = 0
    listing_dates: list[date] = []

    for raw in _records(payload):
        symbol = str(raw.get("公司代號") or "").strip()
        if not COMMON_STOCK_SYMBOL.fullmatch(symbol) or symbol.startswith("91"):
            excluded += 1
            continue
        source_name = str(
            raw.get("公司名稱") or raw.get("公司簡稱") or ""
        ).strip()
        listing_date = parse_optional_exchange_date(raw.get("上市日期"))
        if not source_name or listing_date is None:
            raise IngestionError(
                "CURRENT_LISTING_IDENTITY_ROW_INCOMPLETE",
                "A TWSE common-stock profile is missing its name or listing date",
            )

        event_id = f"MOPS:TWSE:{symbol}:{listing_date.isoformat()}"
        listing_period_id = f"RESEARCH:{event_id}"
        registration_id = _registration_id(raw)
        if registration_id is not None:
            registration_id_rows += 1
        row_reasons: list[str] = list(TWSE_CURRENT_LISTING_IDENTITY_REASON_CODES)
        if registration_id is None:
            row_reasons.append("COMPANY_REGISTRATION_ID_UNAVAILABLE")
        row: dict[str, object] = {
            "listing_period_id": listing_period_id,
            "security_id": None,
            "listing_market": "TWSE",
            "asset_type": "COMMON_STOCK",
            "source_symbol": symbol,
            "source_name": source_name,
            "isin": None,
            "effective_from": listing_date.isoformat(),
            "effective_to": None,
            "identity_resolution_status": "UNRESOLVED",
            "source_id": source_id,
            "source_dataset": payload.dataset,
            "source_event_id": event_id,
            "source_version": source_version,
            "source_revision_hash": _row_hash(payload, raw),
            "source_payload_hash": payload.payload_sha256,
            "source_url": payload.source_url,
            "source_row": dict(raw),
            "first_observed_at": observed_at,
            "available_at": observed_at,
            "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
            "usage_scope": "IDENTITY_RESEARCH_ONLY",
            "system_status": "RESEARCH_ONLY",
            "reason_codes": row_reasons,
        }
        previous = normalized.get(event_id)
        if previous is not None and previous != row:
            raise IngestionError(
                "CURRENT_LISTING_IDENTITY_DUPLICATE_CONFLICT",
                "One MOPS snapshot contains conflicting listing identity rows",
            )
        normalized[event_id] = row
        listing_dates.append(listing_date)

    if not normalized:
        raise IngestionError(
            "CURRENT_LISTING_IDENTITY_EMPTY",
            "MOPS returned no usable TWSE common-stock listing identities",
        )
    return NormalizedTwseCurrentListingIdentities(
        rows=tuple(normalized[key] for key in sorted(normalized)),
        excluded_non_common_stock_rows=excluded,
        registration_id_rows=registration_id_rows,
        listing_date_min=min(listing_dates),
        listing_date_max=max(listing_dates),
    )
