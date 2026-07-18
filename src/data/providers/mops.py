"""MOPS datasets exposed by the official TWSE and TPEx OpenAPI services."""

from __future__ import annotations

from .base import JsonProviderClient
from .contracts import ProviderPayload
from .validation import require_dataset


MOPS_DATASETS = {
    "listed_company_profile": ("https://openapi.twse.com.tw/v1", "/opendata/t187ap03_L"),
    "listed_monthly_revenue": ("https://openapi.twse.com.tw/v1", "/opendata/t187ap05_L"),
    "listed_income_statement_general": (
        "https://openapi.twse.com.tw/v1",
        "/opendata/t187ap06_L_ci",
    ),
    "listed_balance_sheet_general": (
        "https://openapi.twse.com.tw/v1",
        "/opendata/t187ap07_L_ci",
    ),
    "otc_company_profile": (
        "https://www.tpex.org.tw/openapi/v1",
        "/mopsfin_t187ap03_O",
    ),
    "otc_monthly_revenue": (
        "https://www.tpex.org.tw/openapi/v1",
        "/mopsfin_t187ap05_O",
    ),
    "otc_income_statement_general": (
        "https://www.tpex.org.tw/openapi/v1",
        "/mopsfin_t187ap06_O_ci",
    ),
    "otc_balance_sheet_general": (
        "https://www.tpex.org.tw/openapi/v1",
        "/mopsfin_t187ap07_O_ci",
    ),
}


class MopsClient(JsonProviderClient):
    provider_name = "MOPS"
    source_version = "exchange-openapi.v1"
    base_url = "https://openapi.twse.com.tw/v1"

    def fetch(self, dataset: str) -> ProviderPayload:
        name = require_dataset(dataset, MOPS_DATASETS)
        base_url, path = MOPS_DATASETS[name]
        return self._get(
            dataset=name,
            base_url=base_url,
            path=path,
            request_metadata={
                "distribution": "MOPS_VIA_EXCHANGE_OPENAPI",
                "available_at_policy": "use_announcement_time_not_period_end",
            },
        )
