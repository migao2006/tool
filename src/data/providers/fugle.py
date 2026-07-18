"""Fugle MarketData v1 historical candle client."""

from __future__ import annotations

from datetime import date

from .base import JsonProviderClient
from .contracts import ProviderPayload
from .errors import ProviderConfigurationError, ProviderPayloadError
from .validation import iso_date_range, require_path_segment


class FugleClient(JsonProviderClient):
    provider_name = "FUGLE"
    source_version = "marketdata.v1.0"
    base_url = "https://api.fugle.tw/marketdata/v1.0/stock"

    def __init__(self, *, api_key: str | None, http=None) -> None:
        super().__init__(http=http)
        self._api_key = api_key.strip() if api_key else None

    def historical_candles(
        self,
        symbol: str,
        *,
        start_date: date | str,
        end_date: date | str,
        adjusted: bool = False,
    ) -> ProviderPayload:
        if not self._api_key:
            raise ProviderConfigurationError(
                "FUGLE_API_KEY_MISSING",
                "FUGLE_API_KEY is required for Fugle market data",
            )
        normalized_symbol = require_path_segment(symbol, field="symbol")
        normalized_start, normalized_end = iso_date_range(start_date, end_date)
        result = self._get(
            dataset="historical_candles",
            path=f"historical/candles/{normalized_symbol}",
            params={
                "from": normalized_start,
                "to": normalized_end,
                "timeframe": "D",
                "adjusted": str(adjusted).lower(),
                "fields": "open,high,low,close,volume,turnover,change",
            },
            headers={"X-API-KEY": self._api_key},
            request_metadata={
                "symbol": normalized_symbol,
                "adjusted": str(adjusted).lower(),
            },
        )
        if not isinstance(result.payload, dict) or not isinstance(result.payload.get("data"), list):
            raise ProviderPayloadError(
                "FUGLE_PAYLOAD_INVALID",
                "Fugle response does not contain a data array",
            )
        return result
