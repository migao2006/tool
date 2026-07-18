"""Taipei Exchange official OpenAPI client."""

from __future__ import annotations

from .base import JsonProviderClient
from .contracts import ProviderPayload
from .validation import require_dataset


TPEX_DATASETS = {
    "securities": "/tpex_securities",
    "daily_bars": "/tpex_mainboard_daily_close_quotes",
    "market_index": "/tpex_index",
    "margin_balance": "/tpex_mainboard_margin_balance",
    "institutional_flows": "/tpex_3insti_daily_trading",
    "margin_and_lending": "/tpex_margin_sbl",
    "short_and_lending_flow": "/tpex_short_sell",
    "suspended_today": "/tpex_spendi_today",
    "suspended_history": "/tpex_spendi_history",
    "trading_restrictions": "/tpex_cmode",
    "attention": "/tpex_trading_warning_information",
    "disposals": "/tpex_disposal_information",
    "ex_rights": "/tpex_exright_daily",
    "ex_rights_forecast": "/tpex_exright_prepost",
}


class TpexClient(JsonProviderClient):
    provider_name = "TPEX"
    source_version = "openapi.v1"
    base_url = "https://www.tpex.org.tw/openapi/v1"

    def fetch(self, dataset: str) -> ProviderPayload:
        name = require_dataset(dataset, TPEX_DATASETS)
        return self._get(
            dataset=name,
            path=TPEX_DATASETS[name],
            request_metadata={"available_at_policy": "assign_during_ingestion"},
        )
