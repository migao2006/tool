"""Normalize FinMind TAIEX total-return rows without promoting PIT status."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from hashlib import sha256
import json
import math
from typing import cast

from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError
from .historical_benchmark_contracts import (
    BENCHMARK_DATASET,
    BENCHMARK_DATA_ID,
    BENCHMARK_REASON_CODES,
    NormalizedHistoricalBenchmarkBatch,
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
            "HISTORICAL_BENCHMARK_JSON_INVALID",
            "FinMind benchmark row is not canonical JSON",
        ) from error
    return sha256(encoded).hexdigest()


def _source_rows(payload: ProviderPayload) -> list[object]:
    raw = cast(object, payload.payload)
    if not isinstance(raw, Mapping):
        raise IngestionError(
            "HISTORICAL_BENCHMARK_PAYLOAD_INVALID",
            "FinMind benchmark payload must contain a data array",
        )
    rows = cast(Mapping[str, object], raw).get("data")
    if not isinstance(rows, list):
        raise IngestionError(
            "HISTORICAL_BENCHMARK_PAYLOAD_INVALID",
            "FinMind benchmark payload must contain a data array",
        )
    return cast(list[object], rows)


def _parse_date(value: object) -> tuple[str | None, str | None]:
    source_date = "" if value is None else str(value).strip()
    if not source_date:
        return None, None
    try:
        return date.fromisoformat(source_date).isoformat(), source_date
    except ValueError:
        return None, source_date


def _parse_price(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _parse_row(
    payload: ProviderPayload,
    *,
    raw: object,
    row_index: int,
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    source_row: object = raw
    row: Mapping[str, object] = (
        cast(Mapping[str, object], raw)
        if isinstance(raw, Mapping)
        else cast(Mapping[str, object], {})
    )
    source_symbol = str(row.get("stock_id", "")).strip() or None
    trade_date, source_date = _parse_date(row.get("date"))
    price = _parse_price(row.get("price"))
    issues: list[tuple[str, str]] = []
    if not isinstance(raw, Mapping):
        issues.append(("ROW_NOT_OBJECT", "*"))
    if source_symbol != BENCHMARK_DATA_ID:
        issues.append(("BENCHMARK_DATA_ID_MISMATCH", "stock_id"))
    if trade_date is None:
        issues.append(("OBSERVATION_DATE_INVALID", "date"))
    if price is None:
        issues.append(("BENCHMARK_PRICE_INVALID", "price"))
    revision_hash = _canonical_hash(
        {
            "provider": payload.provider,
            "dataset": payload.dataset,
            "row": source_row,
        }
    )
    landing_key = _canonical_hash(
        {
            "dataset": payload.dataset,
            "payload_sha256": payload.payload_sha256,
            "row_index": row_index,
            "source_revision_hash": revision_hash,
        }
    )
    reason_codes = [*BENCHMARK_REASON_CODES, *(reason for reason, _ in issues)]
    observed_at = payload.retrieved_at.isoformat()
    normalized: dict[str, object] = {
        "landing_key": landing_key,
        "source_code": payload.provider,
        "source_dataset": payload.dataset,
        "source_symbol": source_symbol,
        "source_version": payload.source_version,
        "source_revision_hash": revision_hash,
        "source_payload_hash": payload.payload_sha256,
        "source_url": payload.source_url,
        "source_row_index": row_index,
        "source_row": source_row,
        "first_observed_at": observed_at,
        "available_at": observed_at,
        "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
        "point_in_time_status": "UNVERIFIED",
        "usage_scope": "RAW_LANDING_ONLY",
        "system_status": "RESEARCH_ONLY",
        "reason_codes": reason_codes,
        "source_trade_date": source_date,
        "trade_date": trade_date,
        "price": price,
        "parse_status": "QUARANTINED" if issues else "PARSED",
    }
    quarantine: tuple[dict[str, object], ...] = tuple(
        {
            "landing_key": landing_key,
            "reason_code": reason,
            "field_name": field,
            "source_payload_hash": payload.payload_sha256,
            "first_observed_at": observed_at,
        }
        for reason, field in issues
    )
    return normalized, quarantine


def normalize_historical_benchmark(
    payload: ProviderPayload,
) -> NormalizedHistoricalBenchmarkBatch:
    if payload.provider != "FINMIND" or payload.dataset != BENCHMARK_DATASET:
        raise IngestionError(
            "HISTORICAL_BENCHMARK_SOURCE_INVALID",
            "Only the FinMind total-return benchmark dataset is accepted",
        )
    landing_rows: list[dict[str, object]] = []
    quarantine_rows: list[dict[str, object]] = []
    source_rows = _source_rows(payload)
    for index, raw in enumerate(source_rows):
        normalized, issues = _parse_row(payload, raw=raw, row_index=index)
        landing_rows.append(normalized)
        quarantine_rows.extend(issues)
    return NormalizedHistoricalBenchmarkBatch(
        source_row_count=len(source_rows),
        landing_rows=tuple(landing_rows),
        quarantine_rows=tuple(quarantine_rows),
    )
