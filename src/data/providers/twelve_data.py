"""Twelve Data daily international-market time-series client."""

from __future__ import annotations

from datetime import date

from .base import JsonProviderClient
from .contracts import ProviderPayload
from .errors import ProviderConfigurationError, ProviderPayloadError
from .validation import iso_date_range, require_identifier


class TwelveDataClient(JsonProviderClient):
    provider_name = "TWELVE_DATA"
    source_version = "rest.v1"
    base_url = "https://api.twelvedata.com"

    def __init__(self, *, api_key: str | None, http=None) -> None:
        super().__init__(http=http)
        self._api_key = api_key.strip() if api_key else None

    def time_series(
        self,
        symbol: str,
        *,
        start_date: date | str,
        end_date: date | str,
        outputsize: int = 5000,
    ) -> ProviderPayload:
        if not self._api_key:
            raise ProviderConfigurationError(
                "TWELVE_DATA_API_KEY_MISSING",
                "TWELVE_DATA_API_KEY is required for international market data",
            )
        if not 1 <= outputsize <= 5000:
            raise ValueError("outputsize must be between 1 and 5000")
        normalized_symbol = require_identifier(symbol, field="symbol")
        normalized_start, normalized_end = iso_date_range(start_date, end_date)
        result = self._get(
            dataset="time_series",
            path="time_series",
            params={
                "symbol": normalized_symbol,
                "interval": "1day",
                "start_date": normalized_start,
                "end_date": normalized_end,
                "outputsize": outputsize,
                "timezone": "UTC",
                "order": "asc",
                "format": "JSON",
                "apikey": self._api_key,
            },
            sensitive_query_keys=("apikey",),
            request_metadata={
                "symbol": normalized_symbol,
                "available_at_policy": "align_exchange_close_to_taiwan_decision_at",
            },
        )
        if not isinstance(result.payload, dict) or result.payload.get("status") == "error":
            raise ProviderPayloadError(
                "TWELVE_DATA_REQUEST_REJECTED",
                "Twelve Data rejected the requested time series",
            )
        if not isinstance(result.payload.get("values"), list):
            raise ProviderPayloadError(
                "TWELVE_DATA_PAYLOAD_INVALID",
                "Twelve Data response does not contain values",
            )
        return result
