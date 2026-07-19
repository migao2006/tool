"""Taiwan Stock Exchange official OpenAPI client."""

from __future__ import annotations

from datetime import date

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
    "delisting_registry": "/company/suspendListingCsvAndHtml",
}

TAIEX_MONTHLY_OHLC_DATASET = "taiex_price_index_ohlc"
TAIEX_MONTHLY_OHLC_SOURCE_VERSION = "rwd.en.TAIEX.MI_5MINS_HIST.v1"


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


class TwseClient(JsonProviderClient):
    provider_name: str = "TWSE"
    source_version: str = "openapi.v1"
    base_url: str = "https://openapi.twse.com.tw/v1"

    def fetch(self, dataset: str) -> ProviderPayload:
        name = require_dataset(dataset, TWSE_DATASETS)
        return self._get(
            dataset=name,
            path=TWSE_DATASETS[name],
            request_metadata={"available_at_policy": "assign_during_ingestion"},
        )

    def fetch_taiex_monthly_ohlc(self, month: date | str) -> ProviderPayload:
        """Fetch one Gregorian calendar month from the official English RWD API."""

        requested_month = _gregorian_month(month)
        request_date = requested_month.strftime("%Y%m%d")
        return self._get(
            dataset=TAIEX_MONTHLY_OHLC_DATASET,
            base_url="https://www.twse.com.tw",
            path="/rwd/en/TAIEX/MI_5MINS_HIST",
            params={"date": request_date, "response": "json"},
            request_metadata={
                "requested_month": requested_month.strftime("%Y-%m"),
                "request_date": request_date,
                "calendar": "GREGORIAN",
                "language": "en",
                "available_at_policy": "first_project_retrieval_only",
            },
            source_version=TAIEX_MONTHLY_OHLC_SOURCE_VERSION,
        )
