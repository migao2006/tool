"""Normalize FinMind historical bars into unresolved research-only landing rows."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import cast

from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError
from .historical_daily_bar_contracts import (
    HISTORICAL_DAILY_BAR_REASON_CODES,
    NormalizedHistoricalDailyBarBatch,
)


EXPECTED_SOURCE = ("FINMIND", "daily_bars")


def _canonical_hash(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _data_rows(payload: ProviderPayload) -> list[object]:
    raw = cast(object, payload.payload)
    if not isinstance(raw, Mapping):
        raise IngestionError(
            "HISTORICAL_DAILY_BAR_PAYLOAD_INVALID",
            "FinMind daily-bar payload must be an object with a data array",
        )
    data = cast(Mapping[str, object], raw).get("data")
    if not isinstance(data, list):
        raise IngestionError(
            "HISTORICAL_DAILY_BAR_PAYLOAD_INVALID",
            "FinMind daily-bar payload must be an object with a data array",
        )
    return cast(list[object], data)


def _decimal_text(value: object) -> tuple[str | None, bool]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, False
    if isinstance(value, bool):
        return None, True
    text = str(value).strip().replace(",", "")
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None, True
    if not parsed.is_finite():
        return None, True
    return str(parsed), False


def _integer(value: object) -> tuple[int | None, bool]:
    text, invalid = _decimal_text(value)
    if invalid or text is None:
        return None, invalid
    parsed = Decimal(text)
    if parsed != parsed.to_integral_value():
        return None, True
    return int(parsed), False


def _symbol(row: Mapping[str, object]) -> str | None:
    value = row.get("stock_id")
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _trade_date(row: Mapping[str, object]) -> tuple[str | None, str | None]:
    value = row.get("date")
    source_value = None if value is None else str(value).strip() or None
    if source_value is None:
        return None, None
    try:
        return date.fromisoformat(source_value).isoformat(), source_value
    except ValueError:
        return None, source_value


def _landing_key(
    payload: ProviderPayload,
    *,
    symbol: str | None,
    trade_date: str | None,
    row_index: int,
    revision_hash: str,
) -> str:
    if symbol is not None and trade_date is not None:
        identity: object = {
            "provider": payload.provider,
            "dataset": payload.dataset,
            "source_symbol": symbol,
            "trade_date": trade_date,
            "source_revision_hash": revision_hash,
        }
    else:
        identity = {
            "provider": payload.provider,
            "dataset": payload.dataset,
            "payload_sha256": payload.payload_sha256,
            "row_index": row_index,
            "source_revision_hash": revision_hash,
        }
    return _canonical_hash(identity)


def _provenance(
    payload: ProviderPayload,
    *,
    raw: object,
    landing_key: str,
    revision_hash: str,
    symbol: str | None,
    row_index: int,
    reason_codes: list[str],
) -> dict[str, object]:
    observed_at = payload.retrieved_at.isoformat()
    return {
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
        "reason_codes": list(reason_codes),
    }


def _parse_row(
    payload: ProviderPayload,
    *,
    raw: object,
    row_index: int,
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    revision_hash = _canonical_hash(
        {
            "provider": payload.provider,
            "dataset": payload.dataset,
            "row": raw,
        }
    )
    row: Mapping[str, object]
    if isinstance(raw, Mapping):
        row = cast(Mapping[str, object], raw)
    else:
        row = {}
    symbol = _symbol(row)
    trade_date, source_trade_date = _trade_date(row)
    reasons: list[str] = list(HISTORICAL_DAILY_BAR_REASON_CODES)
    issues: list[tuple[str, str]] = []

    def issue(reason_code: str, field_name: str) -> None:
        reasons.append(reason_code)
        issues.append((reason_code, field_name))

    if not isinstance(raw, Mapping):
        issue("ROW_NOT_OBJECT", "*")
    if symbol is None:
        issue("SOURCE_SYMBOL_MISSING", "stock_id")
    if trade_date is None:
        issue("TRADE_DATE_INVALID", "date")

    prices: dict[str, str | None] = {}
    for source_field, target_field in (
        ("open", "open_price"),
        ("max", "high_price"),
        ("min", "low_price"),
        ("close", "close_price"),
    ):
        parsed, invalid = _decimal_text(row.get(source_field))
        prices[target_field] = parsed
        if invalid or parsed is None:
            issue(f"{target_field.upper()}_INVALID", source_field)

    volume, invalid_volume = _decimal_text(row.get("Trading_Volume"))
    value, invalid_value = _decimal_text(row.get("Trading_money"))
    trade_count, invalid_count = _integer(row.get("Trading_turnover"))
    if invalid_volume:
        issue("TRADING_VOLUME_INVALID", "Trading_Volume")
    elif volume is not None and Decimal(volume) < 0:
        issue("TRADING_VOLUME_NEGATIVE", "Trading_Volume")
    if invalid_value:
        issue("TRADING_VALUE_INVALID", "Trading_money")
    elif value is not None and Decimal(value) < 0:
        issue("TRADING_VALUE_NEGATIVE", "Trading_money")
    if invalid_count:
        issue("TRADE_COUNT_INVALID", "Trading_turnover")
    elif trade_count is not None and trade_count < 0:
        issue("TRADE_COUNT_NEGATIVE", "Trading_turnover")

    parsed_prices = [prices[name] for name in prices]
    if all(price is not None for price in parsed_prices):
        open_price, high_price, low_price, close_price = (
            Decimal(cast(str, price)) for price in parsed_prices
        )
        if min(open_price, high_price, low_price, close_price) <= 0:
            issue("OHLC_NON_POSITIVE", "ohlc")
        if high_price < max(open_price, close_price, low_price) or low_price > min(
            open_price, close_price, high_price
        ):
            issue("OHLC_RANGE_INVALID", "ohlc")

    landing_key = _landing_key(
        payload,
        symbol=symbol,
        trade_date=trade_date,
        row_index=row_index,
        revision_hash=revision_hash,
    )
    provenance = _provenance(
        payload,
        raw=cast(object, raw),
        landing_key=landing_key,
        revision_hash=revision_hash,
        symbol=symbol,
        row_index=row_index,
        reason_codes=reasons,
    )
    parse_status = "QUARANTINED" if issues else "PARSED"
    landing_row: dict[str, object] = {
        **provenance,
        "source_trade_date": source_trade_date,
        "trade_date": trade_date,
        "parse_status": parse_status,
        **prices,
        "trading_volume": volume,
        "trading_value": value,
        "trade_count": trade_count,
    }
    quarantine_rows: list[dict[str, object]] = []
    for reason_code, field_name in dict.fromkeys(issues):
        quarantine_rows.append(
            {
                "landing_key": landing_key,
                "reason_code": reason_code,
                "field_name": field_name,
                "severity": "HARD_FAIL",
                "issue_detail": "Source row failed historical landing validation",
            }
        )
    return landing_row, tuple(quarantine_rows)


def normalize_historical_daily_bars(
    payload: ProviderPayload,
) -> NormalizedHistoricalDailyBarBatch:
    """Preserve every FinMind row without asserting market or PIT identity."""

    if (payload.provider, payload.dataset) != EXPECTED_SOURCE:
        raise IngestionError(
            "HISTORICAL_DAILY_BAR_SOURCE_INVALID",
            "Historical daily bars must come from the FinMind daily-bars dataset",
        )
    landing_rows: list[dict[str, object]] = []
    quarantine_rows: list[dict[str, object]] = []
    source_rows = _data_rows(payload)
    for index, raw in enumerate(source_rows):
        landing_row, issues = _parse_row(payload, raw=raw, row_index=index)
        landing_rows.append(landing_row)
        quarantine_rows.extend(issues)
    return NormalizedHistoricalDailyBarBatch(
        source_row_count=len(source_rows),
        landing_rows=tuple(landing_rows),
        quarantine_rows=tuple(quarantine_rows),
    )
