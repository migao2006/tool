"""Provider-specific mappings into the stable market-data contract."""

from __future__ import annotations

from math import isfinite
import re
from typing import Iterable, Mapping

from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError
from .roc_date import parse_exchange_date, parse_optional_exchange_date


COMMON_STOCK_SYMBOL = re.compile(r"^[0-9]{4}$")
MISSING_NUMERIC = {"", "-", "--", "---", "N/A", "null", "None"}


def revision_version(payload: ProviderPayload) -> str:
    """Bind a row version to the exact raw response, preserving later revisions."""

    return f"{payload.source_version}+sha256:{payload.payload_sha256[:16]}"


def _records(payload: ProviderPayload) -> list[Mapping[str, object]]:
    if not isinstance(payload.payload, list):
        raise IngestionError("SOURCE_PAYLOAD_INVALID", "expected a list of source records")
    if not all(isinstance(row, Mapping) for row in payload.payload):
        raise IngestionError("SOURCE_PAYLOAD_INVALID", "source records must be objects")
    return list(payload.payload)


def _number(value: object, *, integer: bool = False) -> int | float | None:
    text = str(value or "").strip().replace(",", "")
    if text in MISSING_NUMERIC:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    if not isfinite(parsed):
        return None
    return int(parsed) if integer else parsed


def normalize_company_profiles(
    payload: ProviderPayload,
    *,
    market: str,
    source_id: int,
) -> tuple[list[dict[str, object]], int]:
    """Normalize current MOPS company profiles; ETFs and derivatives are excluded."""

    if market not in {"TWSE", "TPEX"}:
        raise ValueError("market must be TWSE or TPEX")
    rows: dict[str, dict[str, object]] = {}
    excluded = 0
    for raw in _records(payload):
        if market == "TWSE":
            symbol = str(raw.get("公司代號") or "").strip()
            display_name = str(raw.get("公司簡稱") or raw.get("公司名稱") or "").strip()
            listing_value = raw.get("上市日期")
        else:
            # TPEx's MOPS distribution exposes the same company profile in an
            # English-keyed contract. Do not fall back to the looser securities
            # endpoint because that endpoint also contains ETFs and derivatives.
            symbol = str(raw.get("SecuritiesCompanyCode") or "").strip()
            display_name = str(raw.get("CompanyAbbreviation") or raw.get("CompanyName") or "").strip()
            listing_value = raw.get("DateOfListing")
        # 91xx is the exchange-assigned Taiwan Depositary Receipt range, not
        # an ordinary domestic stock. Company profiles alone do not expose a
        # separate asset-type field, so apply the explicit exchange code rule.
        if (
            not COMMON_STOCK_SYMBOL.fullmatch(symbol)
            or symbol.startswith("91")
            or not display_name
        ):
            excluded += 1
            continue
        listing_date = parse_optional_exchange_date(listing_value)
        row: dict[str, object] = {
            "symbol": symbol,
            "display_name": display_name,
            "market": market,
            "asset_type": "COMMON_STOCK",
            "currency": "TWD",
            "source_id": source_id,
        }
        if listing_date is not None:
            row["listing_date"] = listing_date.isoformat()
        rows[symbol] = row
    return list(rows.values()), excluded


def normalize_daily_bars(
    payload: ProviderPayload,
    *,
    market: str,
    source_id: int,
    security_ids: Mapping[tuple[str, str], int],
) -> tuple[list[dict[str, object]], int]:
    """Normalize executable raw OHLCV only for known ordinary-stock securities."""

    if market not in {"TWSE", "TPEX"}:
        raise ValueError("market must be TWSE or TPEX")
    source_version = revision_version(payload)
    available_at = payload.retrieved_at.isoformat()
    normalized: dict[tuple[int, str], dict[str, object]] = {}
    excluded = 0
    for raw in _records(payload):
        if market == "TWSE":
            symbol = str(raw.get("Code") or "").strip()
            date_value = raw.get("Date")
            open_value, high_value = raw.get("OpeningPrice"), raw.get("HighestPrice")
            low_value, close_value = raw.get("LowestPrice"), raw.get("ClosingPrice")
            volume_value, turnover_value = raw.get("TradeVolume"), raw.get("TradeValue")
            trade_count_value = raw.get("Transaction")
        else:
            symbol = str(raw.get("SecuritiesCompanyCode") or "").strip()
            date_value = raw.get("Date")
            open_value, high_value = raw.get("Open"), raw.get("High")
            low_value, close_value = raw.get("Low"), raw.get("Close")
            volume_value, turnover_value = raw.get("TradingShares"), raw.get("TransactionAmount")
            trade_count_value = raw.get("TransactionNumber")

        security_id = security_ids.get((market, symbol))
        if security_id is None:
            excluded += 1
            continue
        try:
            trade_date = parse_exchange_date(date_value).isoformat()
        except IngestionError:
            excluded += 1
            continue
        raw_open, raw_high = _number(open_value), _number(high_value)
        raw_low, raw_close = _number(low_value), _number(close_value)
        normalized[(security_id, trade_date)] = {
            "security_id": security_id,
            "trade_date": trade_date,
            "raw_open": raw_open,
            "raw_high": raw_high,
            "raw_low": raw_low,
            "raw_close": raw_close,
            "volume_shares": _number(volume_value, integer=True),
            "turnover_ntd": _number(turnover_value, integer=True),
            "trade_count": _number(trade_count_value, integer=True),
            "adjustment_factor": None,
            "cash_dividend_per_share": 0,
            # Corporate actions are intentionally not guessed. These rows stay
            # ineligible for production labels until that source is imported.
            "company_action_complete": False,
            "opening_trade_available": raw_open is not None,
            "closing_trade_available": raw_close is not None,
            "limit_up_price": None,
            "limit_down_price": None,
            "best_bid": None,
            "best_ask": None,
            "source_id": source_id,
            "source_version": source_version,
            "available_at": available_at,
        }
    return list(normalized.values()), excluded


def data_source_rows() -> list[dict[str, object]]:
    return [
        {
            "source_code": "MOPS",
            "display_name": "公開資訊觀測站（交易所 OpenAPI 發布）",
            "source_timezone": "Asia/Taipei",
            "revision_policy": "PAYLOAD_HASH_VERSIONED",
            "is_active": True,
        },
        {
            "source_code": "TWSE",
            "display_name": "臺灣證券交易所 OpenAPI",
            "source_timezone": "Asia/Taipei",
            "revision_policy": "PAYLOAD_HASH_VERSIONED",
            "is_active": True,
        },
        {
            "source_code": "TPEX",
            "display_name": "證券櫃檯買賣中心 OpenAPI",
            "source_timezone": "Asia/Taipei",
            "revision_policy": "PAYLOAD_HASH_VERSIONED",
            "is_active": True,
        },
    ]
