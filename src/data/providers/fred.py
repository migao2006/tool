"""FRED/ALFRED point-in-time series observations client."""

from __future__ import annotations

from datetime import date
import re

from .base import JsonProviderClient
from .contracts import ProviderPayload
from .errors import ProviderConfigurationError, ProviderPayloadError
from .validation import iso_date, iso_date_range, require_identifier


_FRED_API_KEY_PATTERN = re.compile(r"^[a-z0-9]{32}$")


def _normalize_api_key(api_key: str | None) -> str | None:
    """Accept the common GitHub Secret paste forms without exposing the value."""
    if not api_key:
        return None
    normalized = api_key.strip()
    for _ in range(2):
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in "\"'":
            normalized = normalized[1:-1].strip()
        if normalized.upper().startswith("FRED_API_KEY="):
            normalized = normalized.split("=", 1)[1].strip()
    return normalized or None


class FredClient(JsonProviderClient):
    provider_name = "FRED"
    source_version = "api.v1"
    base_url = "https://api.stlouisfed.org/fred"

    def __init__(self, *, api_key: str | None, http=None) -> None:
        super().__init__(http=http)
        self._api_key = _normalize_api_key(api_key)

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
        if not _FRED_API_KEY_PATTERN.fullmatch(self._api_key):
            raise ProviderConfigurationError(
                "FRED_API_KEY_FORMAT_INVALID",
                "FRED_API_KEY must be a registered 32-character lowercase alphanumeric key",
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
