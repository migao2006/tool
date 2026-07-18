"""FinMind v4 historical Taiwan-market data client."""

from __future__ import annotations

from datetime import date
from typing import cast, final

from .base import JsonProviderClient
from .contracts import ProviderPayload
from .errors import ProviderConfigurationError, ProviderPayloadError
from .http import JsonHttpClient
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


@final
class FinMindClient(JsonProviderClient):
    provider_name: str = "FINMIND"
    source_version: str = "api.v4"
    base_url: str = "https://api.finmindtrade.com/api/v4"

    def __init__(
        self,
        *,
        token: str | None,
        http: JsonHttpClient | None = None,
    ) -> None:
        super().__init__(http=http)
        self._token: str | None = token.strip() if token else None

    def _require_token(self) -> str:
        if not self._token:
            raise ProviderConfigurationError(
                "FINMIND_TOKEN_MISSING",
                "FINMIND_TOKEN is required for scheduled ingestion",
            )
        return self._token

    def fetch_quota(self) -> ProviderPayload:
        """Fetch the documented account request counters without exposing the token."""

        token = self._require_token()
        result = self._get(
            dataset="api_quota",
            base_url="https://api.web.finmindtrade.com",
            path="v2/user_info",
            headers={"Authorization": f"Bearer {token}"},
            source_version="api.web.v2",
            request_metadata={
                "schema_contract": "documented_user_count_and_api_request_limit",
            },
        )
        raw_payload = cast(object, result.payload)
        if not isinstance(raw_payload, dict):
            raise ProviderPayloadError(
                "FINMIND_QUOTA_PAYLOAD_INVALID",
                "FinMind quota response must be a JSON object",
            )
        body = cast(dict[str, object], raw_payload)
        for key in ("user_count", "api_request_limit"):
            value = body.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ProviderPayloadError(
                    "FINMIND_QUOTA_PAYLOAD_INVALID",
                    f"FinMind quota response is missing documented field: {key}",
                )
        return result

    def fetch(
        self,
        dataset: str,
        *,
        data_id: str | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> ProviderPayload:
        token = self._require_token()
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
            headers={"Authorization": f"Bearer {token}"},
            request_metadata={
                "remote_dataset": FINMIND_DATASETS[name],
                "available_at_policy": "preserve_provider_release_or_ingestion_time",
            },
        )
        raw_payload = cast(object, result.payload)
        if not isinstance(raw_payload, dict):
            raise ProviderPayloadError(
                "FINMIND_PAYLOAD_INVALID",
                "FinMind response does not contain a data array",
            )
        body = cast(dict[str, object], raw_payload)
        if not isinstance(body.get("data"), list):
            raise ProviderPayloadError(
                "FINMIND_PAYLOAD_INVALID",
                "FinMind response does not contain a data array",
            )
        status = body.get("status")
        if status not in (None, 200):
            raise ProviderPayloadError(
                "FINMIND_REQUEST_REJECTED",
                "FinMind rejected the requested dataset",
            )
        return result
