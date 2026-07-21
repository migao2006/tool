from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.historical_supplemental_normalizer import (
    normalize_historical_supplemental,
)
from src.data.providers.contracts import ProviderPayload


def _payload(dataset: str, rows: list[object]) -> ProviderPayload:
    body = {"status": 200, "data": rows}
    digest = sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ProviderPayload(
        provider="FINMIND",
        dataset=dataset,
        source_version="api.v4",
        source_url="https://api.finmindtrade.com/api/v4/data",
        retrieved_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        payload_sha256=digest,
        payload=body,
    )


@pytest.mark.parametrize(
    "dataset",
    ["adjusted_bars", "institutional_flows", "margin_short"],
)
def test_supported_datasets_preserve_raw_rows_as_research_only(dataset: str) -> None:
    raw = {"date": "2021-07-19", "stock_id": "2330", "value": 123}

    batch = normalize_historical_supplemental(_payload(dataset, [raw]))

    assert batch.source_dataset == dataset
    assert batch.parsed_count == 1
    assert batch.quarantined_count == 0
    row = batch.landing_rows[0]
    assert row["source_row"] == raw
    assert row["available_at_basis"] == "FIRST_OBSERVED_AT_RETRIEVAL"
    assert row["point_in_time_status"] == "UNVERIFIED"
    assert row["usage_scope"] == "RAW_LANDING_ONLY"
    assert row["system_status"] == "RESEARCH_ONLY"


def test_invalid_identity_and_date_are_preserved_but_quarantined() -> None:
    batch = normalize_historical_supplemental(_payload("adjusted_bars", [{"x": 1}]))

    assert batch.source_row_count == 1
    assert batch.quarantined_count == 1
    assert {issue["reason_code"] for issue in batch.quarantine_rows} == {
        "SOURCE_SYMBOL_MISSING",
        "TRADE_DATE_INVALID",
    }


def test_unapproved_dataset_fails_closed() -> None:
    with pytest.raises(IngestionError) as captured:
        normalize_historical_supplemental(_payload("monthly_revenue", []))

    assert captured.value.reason_code == "HISTORICAL_SUPPLEMENTAL_SOURCE_INVALID"
