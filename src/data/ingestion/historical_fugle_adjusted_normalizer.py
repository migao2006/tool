"""Normalize Fugle adjusted candles without making them execution prices."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import cast

from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError
from .historical_fugle_adjusted_provider import (
    FUGLE_ADJUSTED_DATASET,
    FUGLE_REMOTE_DATASET,
)
from .historical_supplemental_contracts import (
    SUPPLEMENTAL_REASON_CODES,
    NormalizedHistoricalSupplementalBatch,
)


FUGLE_ADJUSTED_REASON_CODES = (
    *SUPPLEMENTAL_REASON_CODES,
    "ADJUSTED_FOR_FEATURES_AND_RETURNS_ONLY",
    "NOT_EXECUTION_PRICE_SOURCE",
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
            "Fugle adjusted row is not canonical JSON",
        ) from error
    return sha256(encoded).hexdigest()


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() and parsed > 0 else None


def _trade_date(value: object) -> tuple[str | None, str | None]:
    raw = "" if value is None else str(value).strip()
    if not raw:
        return None, None
    try:
        return date.fromisoformat(raw).isoformat(), raw
    except ValueError:
        return None, raw


def _ohlc_issues(row: Mapping[str, object]) -> list[tuple[str, str]]:
    prices = {
        name: _decimal(row.get(name)) for name in ("open", "high", "low", "close")
    }
    issues = [
        ("ADJUSTED_OHLC_INVALID", name)
        for name, value in prices.items()
        if value is None
    ]
    if issues:
        return issues
    open_price = cast(Decimal, prices["open"])
    high_price = cast(Decimal, prices["high"])
    low_price = cast(Decimal, prices["low"])
    close_price = cast(Decimal, prices["close"])
    if not (
        low_price <= open_price <= high_price and low_price <= close_price <= high_price
    ):
        return [("ADJUSTED_OHLC_INVARIANT_FAILED", "open,high,low,close")]
    return []


def normalize_fugle_adjusted_bars(
    payload: ProviderPayload,
) -> NormalizedHistoricalSupplementalBatch:
    if (
        payload.provider != "FUGLE"
        or payload.dataset != FUGLE_ADJUSTED_DATASET
        or payload.request_metadata.get("remote_dataset") != FUGLE_REMOTE_DATASET
        or payload.request_metadata.get("adjusted") != "true"
    ):
        raise IngestionError(
            "FUGLE_ADJUSTED_SOURCE_INVALID",
            "Only Fugle adjusted daily candles may use this normalizer",
        )
    raw_payload = cast(object, payload.payload)
    if not isinstance(raw_payload, Mapping):
        raise IngestionError(
            "HISTORICAL_SUPPLEMENTAL_PAYLOAD_INVALID",
            "Fugle adjusted payload must be a JSON object",
        )
    body = cast(Mapping[str, object], raw_payload)
    rows_value = body.get("data")
    if not isinstance(rows_value, list):
        raise IngestionError(
            "HISTORICAL_SUPPLEMENTAL_PAYLOAD_INVALID",
            "Fugle adjusted payload must contain a data array",
        )
    symbol_value = body.get("symbol") or payload.request_metadata.get("symbol")
    symbol = "" if symbol_value is None else str(symbol_value).strip()
    if not symbol:
        raise IngestionError(
            "FUGLE_ADJUSTED_SYMBOL_MISSING",
            "Fugle adjusted payload must identify its symbol",
        )
    if symbol != payload.request_metadata.get("symbol"):
        raise IngestionError(
            "FUGLE_ADJUSTED_SYMBOL_MISMATCH",
            "Fugle adjusted response symbol does not match the request",
        )
    timeframe = body.get("timeframe")
    if timeframe is not None and timeframe != "D":
        raise IngestionError(
            "FUGLE_ADJUSTED_TIMEFRAME_INVALID",
            "Fugle adjusted archive accepts daily candles only",
        )

    source_rows = cast(list[object], rows_value)
    landing_rows: list[dict[str, object]] = []
    quarantine_rows: list[dict[str, object]] = []
    observed_at = payload.retrieved_at.isoformat()
    for row_index, raw in enumerate(source_rows):
        source_row: object = raw
        row: Mapping[str, object] = (
            cast(Mapping[str, object], raw)
            if isinstance(raw, Mapping)
            else dict[str, object]()
        )
        trade_date, source_trade_date = _trade_date(row.get("date"))
        issues: list[tuple[str, str]] = []
        if not isinstance(raw, Mapping):
            issues.append(("ROW_NOT_OBJECT", "*"))
        if trade_date is None:
            issues.append(("TRADE_DATE_INVALID", "date"))
        issues.extend(_ohlc_issues(row))
        revision_hash = _canonical_hash(
            {
                "provider": payload.provider,
                "dataset": payload.dataset,
                "row": source_row,
            }
        )
        landing_key = _canonical_hash(
            {
                "provider": payload.provider,
                "dataset": payload.dataset,
                "source_symbol": symbol,
                "trade_date": trade_date,
                "payload_sha256": payload.payload_sha256,
                "row_index": row_index,
                "source_revision_hash": revision_hash,
            }
        )
        reason_codes = [*FUGLE_ADJUSTED_REASON_CODES, *(code for code, _ in issues)]
        landing_rows.append(
            {
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
                "source_row": source_row,
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
        )
        quarantine_rows.extend(
            {
                "landing_key": landing_key,
                "reason_code": reason,
                "field_name": field,
                "source_payload_hash": payload.payload_sha256,
                "first_observed_at": observed_at,
            }
            for reason, field in issues
        )
    return NormalizedHistoricalSupplementalBatch(
        source_dataset=payload.dataset,
        source_row_count=len(source_rows),
        landing_rows=tuple(landing_rows),
        quarantine_rows=tuple(quarantine_rows),
    )
