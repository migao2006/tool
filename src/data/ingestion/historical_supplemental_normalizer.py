"""Preserve FinMind supplemental history as unresolved research-only rows."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from hashlib import sha256
import json
from typing import cast

from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError
from .historical_supplemental_contracts import (
    SUPPLEMENTAL_DATASETS,
    SUPPLEMENTAL_REASON_CODES,
    NormalizedHistoricalSupplementalBatch,
)


def _canonical_hash(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise IngestionError(
            "HISTORICAL_SUPPLEMENTAL_JSON_INVALID",
            "FinMind supplemental row is not canonical JSON",
        ) from error
    return sha256(encoded).hexdigest()


def _data_rows(payload: ProviderPayload) -> list[object]:
    raw = cast(object, payload.payload)
    if not isinstance(raw, Mapping):
        raise IngestionError(
            "HISTORICAL_SUPPLEMENTAL_PAYLOAD_INVALID",
            "FinMind supplemental payload must contain a data array",
        )
    data = cast(Mapping[str, object], raw).get("data")
    if not isinstance(data, list):
        raise IngestionError(
            "HISTORICAL_SUPPLEMENTAL_PAYLOAD_INVALID",
            "FinMind supplemental payload must contain a data array",
        )
    return cast(list[object], data)


def _symbol(row: Mapping[str, object]) -> str | None:
    value = row.get("stock_id")
    normalized = "" if value is None else str(value).strip()
    return normalized or None


def _trade_date(row: Mapping[str, object]) -> tuple[str | None, str | None]:
    value = row.get("date")
    source_value = "" if value is None else str(value).strip()
    if not source_value:
        return None, None
    try:
        return date.fromisoformat(source_value).isoformat(), source_value
    except ValueError:
        return None, source_value


def _parse_row(
    payload: ProviderPayload,
    *,
    raw: object,
    row_index: int,
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    row: Mapping[str, object]
    if isinstance(raw, Mapping):
        row = cast(Mapping[str, object], raw)
    else:
        row = {}
    symbol = _symbol(row)
    trade_date, source_trade_date = _trade_date(row)
    revision_input: dict[str, object] = {
        "provider": payload.provider,
        "dataset": payload.dataset,
        "row": raw,
    }
    revision_hash = _canonical_hash(revision_input)
    identity = {
        "provider": payload.provider,
        "dataset": payload.dataset,
        "source_symbol": symbol,
        "trade_date": trade_date,
        "payload_sha256": payload.payload_sha256,
        "row_index": row_index,
        "source_revision_hash": revision_hash,
    }
    landing_key = _canonical_hash(identity)
    reason_codes: list[str] = list(SUPPLEMENTAL_REASON_CODES)
    issues: list[tuple[str, str]] = []
    if not isinstance(raw, Mapping):
        issues.append(("ROW_NOT_OBJECT", "*"))
    if symbol is None:
        issues.append(("SOURCE_SYMBOL_MISSING", "stock_id"))
    if trade_date is None:
        issues.append(("TRADE_DATE_INVALID", "date"))
    reason_codes.extend(reason for reason, _ in issues)
    observed_at = payload.retrieved_at.isoformat()
    normalized: dict[str, object] = {
        "landing_key": landing_key,
        "source_code": payload.provider,
        "source_dataset": payload.dataset,
        "source_symbol": symbol,
        "source_market_claim": None,
        "source_market_basis": "UNAVAILABLE",
        "source_version": payload.source_version,
        "source_revision_hash": revision_hash,
        "source_payload_hash": payload.payload_sha256,
        "source_url": payload.source_url,
        "source_row_index": row_index,
        "source_row": raw,
        "first_observed_at": observed_at,
        "available_at": observed_at,
        "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
        "identity_resolution_status": "UNRESOLVED",
        "point_in_time_status": "UNVERIFIED",
        "usage_scope": "RAW_LANDING_ONLY",
        "system_status": "RESEARCH_ONLY",
        "reason_codes": reason_codes,
        "source_trade_date": source_trade_date,
        "trade_date": trade_date,
        "parse_status": "QUARANTINED" if issues else "PARSED",
    }
    quarantine_rows: list[dict[str, object]] = [
        {
            "landing_key": landing_key,
            "reason_code": reason,
            "field_name": field,
            "source_payload_hash": payload.payload_sha256,
            "first_observed_at": observed_at,
        }
        for reason, field in issues
    ]
    return normalized, tuple(quarantine_rows)


def normalize_historical_supplemental(
    payload: ProviderPayload,
) -> NormalizedHistoricalSupplementalBatch:
    if payload.provider != "FINMIND" or payload.dataset not in SUPPLEMENTAL_DATASETS:
        raise IngestionError(
            "HISTORICAL_SUPPLEMENTAL_SOURCE_INVALID",
            "Only supported FinMind supplemental datasets may be archived",
        )
    source_rows = _data_rows(payload)
    landing_rows: list[dict[str, object]] = []
    quarantine_rows: list[dict[str, object]] = []
    for row_index, raw in enumerate(source_rows):
        normalized, issues = _parse_row(payload, raw=raw, row_index=row_index)
        landing_rows.append(normalized)
        quarantine_rows.extend(issues)
    return NormalizedHistoricalSupplementalBatch(
        source_dataset=payload.dataset,
        source_row_count=len(source_rows),
        landing_rows=tuple(landing_rows),
        quarantine_rows=tuple(quarantine_rows),
    )
