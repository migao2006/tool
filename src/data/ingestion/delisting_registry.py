"""Normalize official delisting lists without linking current security identities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from hashlib import sha256
import json
from typing import cast

from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError
from .delisting_registry_contracts import (
    DELISTING_REASON_CODES,
    NormalizedDelistingRegistry,
)
from .normalizers import revision_version
from .roc_date import parse_exchange_date


EXPECTED_SOURCES = {
    "TWSE": ("TWSE", "delisting_registry"),
    "TPEX": ("TPEX", "delisting_registry"),
}
TPEX_FIELDS = (
    "股票代號",
    "公司名稱",
    "終止上櫃日期",
    "終止上櫃原因",
    "公司資料網址",
)


def _twse_records(payload: ProviderPayload) -> list[Mapping[str, object]]:
    raw = cast(object, payload.payload)
    if not isinstance(raw, list):
        raise IngestionError(
            "DELISTING_PAYLOAD_INVALID",
            "TWSE delisting registry must be an array of objects",
        )
    items = cast(list[object], raw)
    if not all(isinstance(row, Mapping) for row in items):
        raise IngestionError(
            "DELISTING_PAYLOAD_INVALID",
            "TWSE delisting registry must be an array of objects",
        )
    return [cast(Mapping[str, object], row) for row in items]


def _tpex_records(payload: ProviderPayload) -> list[Mapping[str, object]]:
    raw = cast(object, payload.payload)
    if not isinstance(raw, Mapping):
        raise IngestionError(
            "DELISTING_PAYLOAD_INVALID",
            "TPEx delisting registry did not return an ok response",
        )
    payload_map = cast(Mapping[str, object], raw)
    if payload_map.get("stat") != "ok":
        raise IngestionError(
            "DELISTING_PAYLOAD_INVALID",
            "TPEx delisting registry did not return an ok response",
        )
    tables_value = payload_map.get("tables")
    if not isinstance(tables_value, list):
        raise IngestionError(
            "DELISTING_PAYLOAD_INVALID",
            "TPEx delisting registry must contain exactly one table",
        )
    tables = cast(list[object], tables_value)
    if len(tables) != 1:
        raise IngestionError(
            "DELISTING_PAYLOAD_INVALID",
            "TPEx delisting registry must contain exactly one table",
        )
    table_value = tables[0]
    if not isinstance(table_value, Mapping):
        raise IngestionError(
            "DELISTING_PAYLOAD_INVALID",
            "TPEx delisting registry table must be an object",
        )
    table = cast(Mapping[str, object], table_value)
    fields_value = table.get("fields")
    if not isinstance(fields_value, list):
        raise IngestionError(
            "DELISTING_SCHEMA_CHANGED",
            "TPEx delisting registry fields changed",
        )
    fields = cast(list[object], fields_value)
    if tuple(fields) != TPEX_FIELDS:
        raise IngestionError(
            "DELISTING_SCHEMA_CHANGED",
            "TPEx delisting registry fields changed",
        )
    data_value = table.get("data")
    total_count = table.get("totalCount")
    if not isinstance(data_value, list):
        raise IngestionError(
            "DELISTING_RESPONSE_TRUNCATED",
            "TPEx delisting registry did not return every advertised row",
        )
    data = cast(list[object], data_value)
    if total_count != len(data):
        raise IngestionError(
            "DELISTING_RESPONSE_TRUNCATED",
            "TPEx delisting registry did not return every advertised row",
        )
    records: list[Mapping[str, object]] = []
    for row in data:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)):
            raise IngestionError(
                "DELISTING_PAYLOAD_INVALID",
                "TPEx delisting registry rows must be arrays",
            )
        values = list(row)
        if len(values) != len(TPEX_FIELDS):
            raise IngestionError(
                "DELISTING_SCHEMA_CHANGED",
                "TPEx delisting registry row width changed",
            )
        records.append(dict(zip(TPEX_FIELDS, values, strict=True)))
    return records


def _row_hash(payload: ProviderPayload, row: Mapping[str, object]) -> str:
    canonical = json.dumps(
        {
            "provider": payload.provider,
            "dataset": payload.dataset,
            "row": dict(row),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _fields(
    market: str,
    row: Mapping[str, object],
) -> tuple[str, str | None, object, str | None]:
    if market == "TWSE":
        return (
            str(row.get("Code") or "").strip(),
            str(row.get("Company") or "").strip() or None,
            row.get("DelistingDate"),
            None,
        )
    return (
        str(row.get("股票代號") or "").strip(),
        str(row.get("公司名稱") or "").strip() or None,
        row.get("終止上櫃日期"),
        str(row.get("終止上櫃原因") or "").strip() or None,
    )


def normalize_delisting_registry(
    payload: ProviderPayload,
    *,
    market: str,
    source_id: int,
) -> NormalizedDelistingRegistry:
    """Return unresolved source events; never infer an immutable security ID."""

    if source_id <= 0:
        raise ValueError("source_id must be positive")
    if (payload.provider, payload.dataset) != EXPECTED_SOURCES.get(market):
        raise IngestionError(
            "DELISTING_SOURCE_INVALID",
            "Delisting provider or dataset does not match the market",
        )
    records = _twse_records(payload) if market == "TWSE" else _tpex_records(payload)
    observed_at = payload.retrieved_at.isoformat()
    normalized: dict[str, dict[str, object]] = {}
    dates: list[date] = []

    for raw in records:
        symbol, source_name, date_value, reason = _fields(market, raw)
        if not symbol or date_value is None or not str(date_value).strip():
            raise IngestionError(
                "DELISTING_ROW_INCOMPLETE",
                "Official delisting row is missing symbol or termination date",
            )
        termination_date = parse_exchange_date(date_value)
        event_id = f"{market}:{symbol}:{termination_date.isoformat()}"
        revision_hash = _row_hash(payload, raw)
        row: dict[str, object] = {
            "listing_market": market,
            "source_symbol": symbol,
            "source_name": source_name,
            "termination_date": termination_date.isoformat(),
            "termination_reason_raw": reason,
            "source_id": source_id,
            "source_dataset": payload.dataset,
            "source_event_id": event_id,
            "source_version": revision_version(payload),
            "source_revision_hash": revision_hash,
            "source_payload_hash": payload.payload_sha256,
            "source_url": payload.source_url,
            "source_row": dict(raw),
            "first_observed_at": observed_at,
            "available_at": observed_at,
            "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
            "record_status": "VERIFIED_DELISTING",
            "identity_resolution_status": "UNRESOLVED",
            "usage_scope": "IDENTITY_RESEARCH_ONLY",
            "system_status": "RESEARCH_ONLY",
            "reason_codes": list(DELISTING_REASON_CODES),
        }
        previous = normalized.get(event_id)
        if previous is not None and previous != row:
            raise IngestionError(
                "DELISTING_DUPLICATE_CONFLICT",
                "One source snapshot contains conflicting delisting revisions",
            )
        normalized[event_id] = row
        dates.append(termination_date)

    if not normalized:
        raise IngestionError(
            "DELISTING_COVERAGE_EMPTY",
            f"{market} delisting registry returned no usable rows",
        )
    return NormalizedDelistingRegistry(
        rows=tuple(normalized[key] for key in sorted(normalized)),
        termination_date_min=min(dates),
        termination_date_max=max(dates),
    )
