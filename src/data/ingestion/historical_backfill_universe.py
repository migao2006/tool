"""Derive a research-only ETF scheduling universe from FinMind metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from src.data.providers.contracts import ProviderPayload
from src.data.providers.validation import require_identifier

from .contracts import IngestionError


_MARKETS = {"twse": "TWSE", "tpex": "TPEX"}


def finmind_etf_schedule_rows(
    payload: ProviderPayload,
) -> tuple[dict[str, object], ...]:
    """Use provider-asserted venue/type only; never infer ETF identity from symbols."""

    if (payload.provider, payload.dataset) != ("FINMIND", "securities"):
        raise IngestionError(
            "FINMIND_ETF_UNIVERSE_SOURCE_INVALID",
            "ETF scheduling metadata must come from FinMind securities",
        )
    raw = cast(object, payload.payload)
    if not isinstance(raw, Mapping):
        raise IngestionError(
            "FINMIND_ETF_UNIVERSE_PAYLOAD_INVALID",
            "FinMind securities response must contain a data array",
        )
    body = cast(Mapping[str, object], raw)
    data = body.get("data")
    if not isinstance(data, list):
        raise IngestionError(
            "FINMIND_ETF_UNIVERSE_PAYLOAD_INVALID",
            "FinMind securities response must contain a data array",
        )
    rows: dict[tuple[str, str], dict[str, object]] = {}
    symbol_markets: dict[str, str] = {}
    for value in cast(list[object], data):
        if not isinstance(value, Mapping):
            continue
        row = cast(Mapping[str, object], value)
        category = str(row.get("industry_category", "")).strip().upper()
        if category != "ETF":
            continue
        market = _MARKETS.get(str(row.get("type", "")).strip().lower())
        if market is None:
            continue
        try:
            symbol = require_identifier(str(row.get("stock_id", "")), field="stock_id")
        except ValueError:
            continue
        if len(symbol) > 32:
            continue
        previous_market = symbol_markets.setdefault(symbol, market)
        if previous_market != market:
            raise IngestionError(
                "FINMIND_ETF_UNIVERSE_MARKET_CONFLICT",
                "FinMind assigned one ETF symbol to multiple markets",
            )
        raw_name = row.get("stock_name")
        display_name = str(raw_name).strip() if raw_name is not None else None
        rows[(market, symbol)] = {
            "source_symbol": symbol,
            "display_name": display_name or None,
            "market": market,
        }
    market_priority = {"TWSE": 0, "TPEX": 1}
    ordered_keys = sorted(rows, key=lambda key: (market_priority[key[0]], key[1]))
    return tuple(rows[key] for key in ordered_keys)
