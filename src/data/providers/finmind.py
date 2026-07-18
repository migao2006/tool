"""FinMind v4 historical Taiwan-market data client."""

from __future__ import annotations

from datetime import date

from .base import JsonProviderClient
from .contracts import ProviderPayload
from .errors import ProviderConfigurationError, ProviderPayloadError
from .validation import iso_date_range, require_dataset, require_identifier


FINMIND_DATASETS = {
    "securities": "TaiwanStockInfo",
    "trading_calendar": "TaiwanStockTradingDate",
    "daily_bars": "TaiwanStockPrice",
    "adjusted_bars": "TaiwanStockPriceAdj",
    "institutional_flows": "TaiwanStockInstitutionalInvestorsBuySellWide",
    "margin_short": "TaiwanStockMarginPurchaseShortSale",
    "securities_lending": "TaiwanStockSecuritiesLending",
    "foreign_shareholding": "TaiwanStockShareholding",
    "holding_distribution": "TaiwanStockHoldingSharesPer",
    "monthly_revenue": "TaiwanStockMonthRevenue",
    "income_statement": "TaiwanStockFinancialStatements",
    "balance_sheet": "TaiwanStockBalanceSheet",
    "cash_flow": "TaiwanStockCashFlowsStatement",
    "dividends": "TaiwanStockDividend",
    "dividend_results": "TaiwanStockDividendResult",
    "delistings": "TaiwanStockDelisting",
    "stock_splits": "TaiwanStockSplitPrice",
    "par_value_changes": "TaiwanStockParValueChange",
    "suspended": "TaiwanStockSuspended",
}


class FinMindClient(JsonProviderClient):
    provider_name = "FINMIND"
    source_version = "api.v4"
    base_url = "https://api.finmindtrade.com/api/v4"

    def __init__(self, *, token: str | None, http=None) -> None:
        super().__init__(http=http)
        self._token = token.strip() if token else None

    def fetch(
        self,
        dataset: str,
        *,
        data_id: str | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> ProviderPayload:
        if not self._token:
            raise ProviderConfigurationError(
                "FINMIND_TOKEN_MISSING",
                "FINMIND_TOKEN is required for scheduled ingestion",
            )
        name = require_dataset(dataset, FINMIND_DATASETS)
        normalized_id = require_identifier(data_id, field="data_id") if data_id else None
        normalized_start, normalized_end = iso_date_range(start_date, end_date)
        result = self._get(
            dataset=name,
            path="data",
            params={
                "dataset": FINMIND_DATASETS[name],
                "data_id": normalized_id,
                "start_date": normalized_start,
                "end_date": normalized_end,
            },
            headers={"Authorization": f"Bearer {self._token}"},
            request_metadata={
                "remote_dataset": FINMIND_DATASETS[name],
                "available_at_policy": "preserve_provider_release_or_ingestion_time",
            },
        )
        if not isinstance(result.payload, dict) or not isinstance(result.payload.get("data"), list):
            raise ProviderPayloadError(
                "FINMIND_PAYLOAD_INVALID",
                "FinMind response does not contain a data array",
            )
        status = result.payload.get("status")
        if status not in (None, 200):
            raise ProviderPayloadError(
                "FINMIND_REQUEST_REJECTED",
                "FinMind rejected the requested dataset",
            )
        return result
