"""Taiwan Stock Exchange official OpenAPI client."""

from __future__ import annotations

from .base import JsonProviderClient
from .contracts import ProviderPayload
from .validation import require_dataset


TWSE_DATASETS = {
    "securities": "/opendata/t187ap03_L",
    "daily_bars": "/exchangeReport/STOCK_DAY_ALL",
    "market_index": "/indicesReport/MI_5MINS_HIST",
    "return_index": "/indicesReport/MFI94U",
    "trading_calendar": "/holidaySchedule/holidaySchedule",
    "margin_balance": "/exchangeReport/MI_MARGN",
    "lendable_shares": "/SBL/TWT96U",
    "suspended": "/exchangeReport/TWTAWU",
    "changed_trading": "/exchangeReport/TWT85U",
    "attention": "/announcement/notice",
    "disposals": "/announcement/punish",
    "ex_rights": "/exchangeReport/TWT48U_ALL",
}


class TwseClient(JsonProviderClient):
    provider_name = "TWSE"
    source_version = "openapi.v1"
    base_url = "https://openapi.twse.com.tw/v1"

    def fetch(self, dataset: str) -> ProviderPayload:
        name = require_dataset(dataset, TWSE_DATASETS)
        return self._get(
            dataset=name,
            path=TWSE_DATASETS[name],
            request_metadata={"available_at_policy": "assign_during_ingestion"},
        )
