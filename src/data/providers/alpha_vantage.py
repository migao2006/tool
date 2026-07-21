"""Alpha Vantage macroeconomic series client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .base import JsonProviderClient
from .contracts import ProviderPayload
from .errors import ProviderConfigurationError, ProviderPayloadError
from .validation import require_dataset


@dataclass(frozen=True)
class MacroDataset:
    function: str
    parameters: Mapping[str, str]


MACRO_DATASETS: Mapping[str, MacroDataset] = {
    "treasury_yield_10y_daily": MacroDataset(
        function="TREASURY_YIELD",
        parameters={"interval": "daily", "maturity": "10year"},
    ),
    "federal_funds_rate_daily": MacroDataset(
        function="FEDERAL_FUNDS_RATE",
        parameters={"interval": "daily"},
    ),
    "cpi_monthly": MacroDataset(
        function="CPI",
        parameters={"interval": "monthly"},
    ),
    "inflation_annual": MacroDataset(function="INFLATION", parameters={}),
    "retail_sales_monthly": MacroDataset(function="RETAIL_SALES", parameters={}),
    "durable_goods_monthly": MacroDataset(function="DURABLES", parameters={}),
    "unemployment_monthly": MacroDataset(function="UNEMPLOYMENT", parameters={}),
    "nonfarm_payroll_monthly": MacroDataset(function="NONFARM_PAYROLL", parameters={}),
    "real_gdp_quarterly": MacroDataset(
        function="REAL_GDP",
        parameters={"interval": "quarterly"},
    ),
}


def _normalize_api_key(api_key: str | None) -> str | None:
    """Accept common secret paste forms without logging the credential."""

    if not api_key:
        return None
    normalized = api_key.strip()
    for _ in range(2):
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in "\"'":
            normalized = normalized[1:-1].strip()
        if normalized.upper().startswith("ALPHA_VANTAGE_API_KEY="):
            normalized = normalized.split("=", 1)[1].strip()
    return normalized or None


class AlphaVantageClient(JsonProviderClient):
    provider_name = "ALPHA_VANTAGE"
    source_version = "query.v1"
    base_url = "https://www.alphavantage.co"

    def __init__(self, *, api_key: str | None, http=None) -> None:
        super().__init__(http=http)
        self._api_key = _normalize_api_key(api_key)

    def fetch_macro(self, dataset: str) -> ProviderPayload:
        if not self._api_key:
            raise ProviderConfigurationError(
                "ALPHA_VANTAGE_API_KEY_MISSING",
                "ALPHA_VANTAGE_API_KEY is required for US macroeconomic data",
            )

        normalized_dataset = require_dataset(dataset, MACRO_DATASETS)
        definition = MACRO_DATASETS[normalized_dataset]
        result = self._get(
            dataset=normalized_dataset,
            path="query",
            params={
                "function": definition.function,
                **definition.parameters,
                "apikey": self._api_key,
            },
            sensitive_query_keys=("apikey",),
            request_metadata={
                "function": definition.function,
                "available_at_policy": "retrieval_timestamp_only",
                "historical_vintage": "unavailable",
            },
        )
        payload = result.payload
        if not isinstance(payload, dict):
            raise ProviderPayloadError(
                "ALPHA_VANTAGE_PAYLOAD_INVALID",
                "Alpha Vantage response must be a JSON object",
            )

        information = str(payload.get("Information", ""))
        note = str(payload.get("Note", ""))
        provider_message = f"{information} {note}".casefold()
        if "rate limit" in provider_message or "call frequency" in provider_message:
            raise ProviderPayloadError(
                "ALPHA_VANTAGE_RATE_LIMITED",
                "Alpha Vantage request reached the configured API limit",
            )
        if payload.get("Error Message") or information or note:
            raise ProviderPayloadError(
                "ALPHA_VANTAGE_REQUEST_REJECTED",
                "Alpha Vantage rejected the requested macroeconomic dataset",
            )
        if not isinstance(payload.get("data"), list):
            raise ProviderPayloadError(
                "ALPHA_VANTAGE_PAYLOAD_INVALID",
                "Alpha Vantage response does not contain macroeconomic observations",
            )
        return result
