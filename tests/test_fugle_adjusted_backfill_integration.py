from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from typing import final

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.historical_archive_contracts import HistoricalArchiveRequest
from src.data.ingestion.historical_daily_bar_archive_service import (
    HistoricalArchiveWriteResult,
)
from src.data.ingestion.historical_fugle_adjusted_provider import (
    FugleAdjustedBackfillProvider,
)
from src.data.ingestion.historical_supplemental_landing_service import (
    HistoricalSupplementalLandingService,
)
from src.data.ingestion.historical_supplemental_normalizer import (
    normalize_historical_supplemental,
)
from src.data.ingestion.historical_supplemental_parquet import (
    serialize_historical_supplemental_parquet,
)
from src.data.providers.contracts import ProviderPayload


START = date(2025, 1, 1)
END = date(2025, 12, 31)


def _remote_payload(*, valid: bool = True) -> ProviderPayload:
    row: dict[str, object] = {
        "date": "2025-06-10",
        "open": 100,
        "high": 110,
        "low": 90,
        "close": 101,
        "volume": 1_000,
    }
    if not valid:
        row["open"] = 120
    body = {"symbol": "2330", "timeframe": "D", "data": [row]}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return ProviderPayload(
        provider="FUGLE",
        dataset="historical_candles",
        source_version="marketdata.v1.0",
        source_url=(
            "https://api.fugle.tw/marketdata/v1.0/stock/"
            "historical/candles/2330?adjusted=true"
        ),
        retrieved_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        payload_sha256=sha256(encoded).hexdigest(),
        payload=body,
        request_metadata={"symbol": "2330", "adjusted": "true"},
    )


@final
class FakeFugleClient:
    def __init__(self, payload: ProviderPayload | None = None) -> None:
        self.payload = payload or _remote_payload()
        self.calls: list[dict[str, object]] = []

    def historical_candles(
        self,
        symbol: str,
        *,
        start_date: date | str,
        end_date: date | str,
        adjusted: bool = False,
    ) -> ProviderPayload:
        self.calls.append(
            {
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date,
                "adjusted": adjusted,
            }
        )
        return self.payload


def test_adapter_maps_only_adjusted_candles_to_logical_dataset() -> None:
    client = FakeFugleClient()

    payload = FugleAdjustedBackfillProvider(client).fetch(
        "adjusted_bars",
        data_id="2330",
        start_date=START,
        end_date=END,
    )

    assert client.calls == [
        {
            "symbol": "2330",
            "start_date": START,
            "end_date": END,
            "adjusted": True,
        }
    ]
    assert payload.provider == "FUGLE"
    assert payload.dataset == "adjusted_bars"
    assert payload.request_metadata["remote_dataset"] == "historical_candles"
    assert payload.request_metadata["adjusted"] == "true"


@pytest.mark.parametrize(
    ("dataset", "start", "end", "reason_code"),
    [
        (
            "institutional_flows",
            START,
            END,
            "FUGLE_ADJUSTED_DATASET_INVALID",
        ),
        (
            "adjusted_bars",
            date(2024, 1, 1),
            date(2025, 1, 2),
            "FUGLE_ADJUSTED_RANGE_LIMIT",
        ),
    ],
)
def test_adapter_rejects_other_datasets_and_multi_year_requests(
    dataset: str,
    start: date,
    end: date,
    reason_code: str,
) -> None:
    client = FakeFugleClient()

    with pytest.raises(IngestionError) as captured:
        _ = FugleAdjustedBackfillProvider(client).fetch(
            dataset,
            data_id="2330",
            start_date=start,
            end_date=end,
        )

    assert captured.value.reason_code == reason_code
    assert client.calls == []


def test_adapter_allows_one_complete_leap_year_but_not_next_new_year() -> None:
    client = FakeFugleClient()
    provider = FugleAdjustedBackfillProvider(client)

    _ = provider.fetch(
        "adjusted_bars",
        data_id="2330",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
    )

    assert len(client.calls) == 1
    with pytest.raises(IngestionError) as captured:
        _ = provider.fetch(
            "adjusted_bars",
            data_id="2330",
            start_date=date(2024, 1, 1),
            end_date=date(2025, 1, 1),
        )
    assert captured.value.reason_code == "FUGLE_ADJUSTED_RANGE_LIMIT"
    assert len(client.calls) == 1


def test_fugle_adjusted_parquet_is_provider_scoped_and_research_only() -> None:
    payload = FugleAdjustedBackfillProvider(FakeFugleClient()).fetch(
        "adjusted_bars",
        data_id="2330",
        start_date=START,
        end_date=END,
    )
    batch = normalize_historical_supplemental(payload)
    row = batch.landing_rows[0]

    assert row["source_code"] == "FUGLE"
    assert row["source_dataset"] == "adjusted_bars"
    assert row["usage_scope"] == "RAW_LANDING_ONLY"
    assert row["system_status"] == "RESEARCH_ONLY"
    reason_codes = row["reason_codes"]
    assert isinstance(reason_codes, list)
    assert "ADJUSTED_FOR_FEATURES_AND_RETURNS_ONLY" in reason_codes
    assert "NOT_EXECUTION_PRICE_SOURCE" in reason_codes

    request = HistoricalArchiveRequest(
        scheduled_market="TWSE",
        asset_type="COMMON_STOCK",
        source_symbol="2330",
        requested_start_date=START,
        requested_end_date=END,
        source_payload_sha256=payload.payload_sha256,
        retrieved_at=payload.retrieved_at,
        source_dataset=payload.dataset,
        provider_code=payload.provider,
    )
    artifact = serialize_historical_supplemental_parquet(
        batch.landing_rows,
        request=request,
    )

    assert artifact.object_key.startswith(
        "raw/v1/provider=fugle/dataset=adjusted_bars/"
    )
    assert artifact.object_metadata()["provider-code"] == "FUGLE"
    parquet = pq.ParquetFile(pa.BufferReader(artifact.payload))
    metadata = parquet.schema_arrow.metadata or {}
    assert metadata[b"archive.provider_code"] == b"FUGLE"
    assert parquet.read().to_pylist()[0]["source_code"] == "FUGLE"


def test_invalid_adjusted_ohlc_is_preserved_but_quarantined() -> None:
    payload = FugleAdjustedBackfillProvider(
        FakeFugleClient(_remote_payload(valid=False))
    ).fetch(
        "adjusted_bars",
        data_id="2330",
        start_date=START,
        end_date=END,
    )

    batch = normalize_historical_supplemental(payload)

    assert batch.source_row_count == 1
    assert batch.quarantined_count == 1
    assert batch.landing_rows[0]["parse_status"] == "QUARANTINED"
    assert {issue["reason_code"] for issue in batch.quarantine_rows} == {
        "ADJUSTED_OHLC_INVARIANT_FAILED"
    }


def test_duplicate_adjusted_trade_date_is_quarantined() -> None:
    payload = _remote_payload()
    body = dict(payload.payload)
    rows = list(body["data"])
    rows.append(dict(rows[0]))
    body["data"] = rows
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    duplicate_payload = ProviderPayload(
        provider=payload.provider,
        dataset=payload.dataset,
        source_version=payload.source_version,
        source_url=payload.source_url,
        retrieved_at=payload.retrieved_at,
        payload_sha256=sha256(encoded).hexdigest(),
        payload=body,
        request_metadata=payload.request_metadata,
    )

    batch = normalize_historical_supplemental(
        FugleAdjustedBackfillProvider(FakeFugleClient(duplicate_payload)).fetch(
            "adjusted_bars",
            data_id="2330",
            start_date=START,
            end_date=END,
        )
    )

    assert batch.source_row_count == 2
    assert batch.quarantined_count == 1
    assert {issue["reason_code"] for issue in batch.quarantine_rows} == {
        "DUPLICATE_TRADE_DATE"
    }


@pytest.mark.parametrize(
    ("market", "asset_type"),
    (("TPEX", "COMMON_STOCK"), ("TWSE", "ETF")),
)
def test_archive_contract_rejects_fugle_outside_twse_common_stock(
    market: str,
    asset_type: str,
) -> None:
    with pytest.raises(ValueError, match="TWSE common stocks"):
        HistoricalArchiveRequest(
            provider_code="FUGLE",
            source_dataset="adjusted_bars",
            scheduled_market=market,
            asset_type=asset_type,
            source_symbol="2330",
            requested_start_date=START,
            requested_end_date=END,
            source_payload_sha256="a" * 64,
            retrieved_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        )


class FakeArchive:
    def __init__(self) -> None:
        self.payloads: list[ProviderPayload] = []

    def archive(
        self,
        *,
        rows: Sequence[Mapping[str, object]],
        quarantine_rows: Sequence[Mapping[str, object]],
        payload: ProviderPayload,
        scheduled_market: str,
        asset_type: str,
        symbol: str,
        start_date: date,
        end_date: date,
        backfill_task_id: int | None,
    ) -> HistoricalArchiveWriteResult:
        _ = (
            quarantine_rows,
            scheduled_market,
            asset_type,
            symbol,
            start_date,
            end_date,
            backfill_task_id,
        )
        self.payloads.append(payload)
        return HistoricalArchiveWriteResult("object", True, "a" * 64, 100, len(rows))


def test_landing_service_keeps_fugle_adjusted_out_of_etf_scope() -> None:
    archive = FakeArchive()
    service = HistoricalSupplementalLandingService(
        provider=FugleAdjustedBackfillProvider(FakeFugleClient()),
        archive_service=archive,
    )

    result = service.land_symbol(
        dataset="adjusted_bars",
        symbol="2330",
        start_date=START,
        end_date=END,
        scheduled_market="TWSE",
        asset_type="COMMON_STOCK",
        backfill_task_id=None,
    )

    assert result.latest_trade_date == "2025-06-10"
    assert archive.payloads[0].provider == "FUGLE"
    with pytest.raises(IngestionError) as captured:
        _ = service.land_symbol(
            dataset="adjusted_bars",
            symbol="0050",
            start_date=START,
            end_date=END,
            scheduled_market="TWSE",
            asset_type="ETF",
            backfill_task_id=None,
        )
    assert captured.value.reason_code == "HISTORICAL_SUPPLEMENTAL_SCOPE_INVALID"
