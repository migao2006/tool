"""Taiwan Futures Exchange official OpenAPI client."""

from __future__ import annotations

from .base import JsonProviderClient
from .contracts import ProviderPayload
from .validation import require_dataset


TAIFEX_DATASETS = {
    "futures_daily": "/DailyMarketReportFut",
    "options_daily": "/DailyMarketReportOpt",
    "put_call_ratio": "/PutCallRatio",
    "institutional_summary": "/MarketDataOfMajorInstitutionalTradersGeneralBytheDate",
    "institutional_futures": (
        "/MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate"
    ),
    "institutional_options": (
        "/MarketDataOfMajorInstitutionalTradersDetailsOfOptionsContractsBytheDate"
    ),
    "institutional_put_call": (
        "/MarketDataOfMajorInstitutionalTradersDetailsOfCallsAndPutsBytheDate"
    ),
    "large_trader_futures_oi": "/OpenInterestOfLargeTradersFutures",
    "large_trader_options_oi": "/OpenInterestOfLargeTradersOptions",
}


class TaifexClient(JsonProviderClient):
    provider_name = "TAIFEX"
    source_version = "openapi.v1"
    base_url = "https://openapi.taifex.com.tw/v1"

    def fetch(self, dataset: str) -> ProviderPayload:
        name = require_dataset(dataset, TAIFEX_DATASETS)
        return self._get(
            dataset=name,
            path=TAIFEX_DATASETS[name],
            request_metadata={"available_at_policy": "assign_during_ingestion"},
        )
