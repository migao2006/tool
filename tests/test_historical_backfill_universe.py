from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.historical_backfill_universe import (
    finmind_etf_schedule_rows,
)
from src.data.providers.contracts import ProviderPayload


def _payload(rows: list[object]) -> ProviderPayload:
    body = {"status": 200, "data": rows}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return ProviderPayload(
        provider="FINMIND",
        dataset="securities",
        source_version="api.v4",
        source_url="https://api.finmindtrade.com/api/v4/data",
        retrieved_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        payload_sha256=sha256(encoded).hexdigest(),
        payload=body,
    )


def test_etf_universe_uses_provider_type_and_never_symbol_guessing() -> None:
    rows = finmind_etf_schedule_rows(
        _payload(
            [
                {
                    "industry_category": "ETF",
                    "stock_id": "006208",
                    "stock_name": "富邦台50",
                    "type": "twse",
                },
                {
                    "industry_category": "ETF",
                    "stock_id": "00679B",
                    "stock_name": "元大美債20年",
                    "type": "tpex",
                },
                {
                    "industry_category": "半導體業",
                    "stock_id": "2330",
                    "stock_name": "台積電",
                    "type": "twse",
                },
                {
                    "industry_category": "ETF",
                    "stock_id": "0050",
                    "stock_name": "未知市場",
                    "type": "other",
                },
            ]
        )
    )
    assert rows == (
        {"source_symbol": "006208", "display_name": "富邦台50", "market": "TWSE"},
        {"source_symbol": "00679B", "display_name": "元大美債20年", "market": "TPEX"},
    )


def test_etf_universe_rejects_conflicting_provider_market_identity() -> None:
    with pytest.raises(IngestionError) as captured:
        finmind_etf_schedule_rows(
            _payload(
                [
                    {
                        "industry_category": "ETF",
                        "stock_id": "0050",
                        "type": "twse",
                    },
                    {
                        "industry_category": "ETF",
                        "stock_id": "0050",
                        "type": "tpex",
                    },
                ]
            )
        )
    assert captured.value.reason_code == "FINMIND_ETF_UNIVERSE_MARKET_CONFLICT"
