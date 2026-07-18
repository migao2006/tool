"""FRED/ALFRED point-in-time series observations client."""

from __future__ import annotations

from datetime import date

from .base import JsonProviderClient
from .contracts import ProviderPayload
from .errors import ProviderConfigurationError, ProviderPayloadError
from .validation import iso_date, iso_date_range, require_identifier


class FredClient(JsonProviderClient):
    provider_name = "FRED"
    source_version = "api.v1"
    base_url = "https://api.stlouisfed.org/fred"

    def __init__(self, *, api_key: str | None, http=None) -> None:
        super().__init__(http=http)
        self._api_key = api_key.strip() if api_key else None

    def observations(
        self,
        series_id: str,
        *,
        as_of_date: date | str,
        observation_start: date | str | None = None,
        observation_end: date | str | None = None,
    ) -> ProviderPayload:
        if not self._api_key:
            raise ProviderConfigurationError(
                "FRED_API_KEY_MISSING",
                "FRED_API_KEY is required for macroeconomic data",
            )
        normalized_series = require_identifier(series_id, field="series_id")
        vintage = iso_date(as_of_date, field="as_of_date")
        normalized_start, normalized_end = iso_date_range(observation_start, observation_end)
        result = self._get(
            dataset="series_observations",
            path="series/observations",
            params={
                "series_id": normalized_series,
                "api_key": self._api_key,
                "file_type": "json",
                "realtime_start": vintage,
                "realtime_end": vintage,
                "observation_start": normalized_start,
                "observation_end": normalized_end,
            },
            sensitive_query_keys=("api_key",),
            request_metadata={
                "series_id": normalized_series,
                "point_in_time_vintage": vintage or "",
            },
        )
        if not isinstance(result.payload, dict) or not isinstance(
            result.payload.get("observations"), list
        ):
            raise ProviderPayloadError(
                "FRED_PAYLOAD_INVALID",
                "FRED response does not contain observations",
            )
        return result
