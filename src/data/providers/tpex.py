"""Taipei Exchange official OpenAPI client."""

from __future__ import annotations

from datetime import date

from .base import JsonProviderClient
from .contracts import ProviderPayload
from .validation import require_dataset


TPEX_DATASETS = {
    "securities": "/tpex_securities",
    "daily_bars": "/tpex_mainboard_daily_close_quotes",
    "market_index": "/tpex_index",
    "return_index": "/tpex_reward_index",
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
    "delisting_registry": "/www/zh-tw/company/deListed",
}

TPEX_WEBSITE_BASE_URL = "https://www.tpex.org.tw"
TPEX_MONTHLY_OHLC_DATASET = "tpex_price_index_ohlc"
TPEX_MONTHLY_OHLC_SOURCE_VERSION = "website.en.indexInfo.inx.v1"


def _gregorian_month(value: date | str) -> date:
    if isinstance(value, date):
        return value.replace(day=1)
    normalized = value.strip()
    try:
        if len(normalized) == 7:
            return date.fromisoformat(f"{normalized}-01")
        return date.fromisoformat(normalized).replace(day=1)
    except ValueError as error:
        raise ValueError("month must use Gregorian YYYY-MM or YYYY-MM-DD") from error


class TpexClient(JsonProviderClient):
    provider_name: str = "TPEX"
    source_version: str = "openapi.v1"
    base_url: str = "https://www.tpex.org.tw/openapi/v1"

    def fetch(self, dataset: str) -> ProviderPayload:
        name = require_dataset(dataset, TPEX_DATASETS)
        if name == "delisting_registry":
            return self._get(
                dataset=name,
                base_url=TPEX_WEBSITE_BASE_URL,
                path=TPEX_DATASETS[name],
                params={
                    "code": "",
                    "date": "ALL",
                    "reason": "-1",
                    "response": "json",
                    "paging-size": 1_000,
                    "paging-offset": 0,
                },
                request_metadata={
                    "available_at_policy": "assign_during_ingestion",
                    "distribution": "OFFICIAL_TPEX_WEBSITE_JSON",
                },
                source_version="website-json.v1",
            )
        return self._get(
            dataset=name,
            path=TPEX_DATASETS[name],
            request_metadata={"available_at_policy": "assign_during_ingestion"},
        )

    def fetch_monthly_index_ohlc(self, month: date | str) -> ProviderPayload:
        """Fetch one Gregorian month of official TPEx price-index OHLC."""

        requested_month = _gregorian_month(month)
        request_date = requested_month.strftime("%Y/%m/01")
        return self._get(
            dataset=TPEX_MONTHLY_OHLC_DATASET,
            base_url=TPEX_WEBSITE_BASE_URL,
            path="/www/en-us/indexInfo/inx",
            params={"date": request_date, "response": "json"},
            request_metadata={
                "requested_month": requested_month.strftime("%Y-%m"),
                "request_date": request_date,
                "calendar": "GREGORIAN",
                "language": "en",
                "available_at_policy": "first_project_retrieval_only",
            },
            source_version=TPEX_MONTHLY_OHLC_SOURCE_VERSION,
        )
