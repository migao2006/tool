from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from hashlib import sha256
import json

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.historical_daily_bar_archive_service import (
    HistoricalArchiveWriteResult,
)
from src.data.ingestion.historical_supplemental_landing_service import (
    HistoricalSupplementalLandingService,
)
from src.data.providers.contracts import ProviderPayload


class FakeProvider:
    def fetch(
        self,
        dataset: str,
        *,
        data_id: str | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> ProviderPayload:
        body = {
            "status": 200,
            "data": [{"date": "2021-07-19", "stock_id": data_id, "value": 1}],
        }
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        return ProviderPayload(
            provider="FINMIND",
            dataset=dataset,
            source_version="api.v4",
            source_url="https://api.finmindtrade.com/api/v4/data",
            retrieved_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
            payload_sha256=sha256(encoded).hexdigest(),
            payload=body,
        )


class FakeArchive:
    def __init__(self) -> None:
        self.datasets: list[str] = []

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
        self.datasets.append(payload.dataset)
        return HistoricalArchiveWriteResult("object", True, "a" * 64, 100, len(rows))


def test_landing_fetches_requested_dataset_and_keeps_research_scope() -> None:
    archive = FakeArchive()
    service = HistoricalSupplementalLandingService(
        provider=FakeProvider(),
        archive_service=archive,
    )

    result = service.land_symbol(
        dataset="adjusted_bars",
        symbol="2330",
        start_date=date(2021, 7, 19),
        end_date=date(2026, 7, 17),
        scheduled_market="TWSE",
        asset_type="COMMON_STOCK",
        backfill_task_id=7,
    )

    assert archive.datasets == ["adjusted_bars"]
    assert result.fetched_rows == result.landed_rows == 1
    assert result.latest_trade_date == "2021-07-19"


def test_first_phase_rejects_non_twse_or_etf_requests() -> None:
    service = HistoricalSupplementalLandingService(
        provider=FakeProvider(),
        archive_service=FakeArchive(),
    )
    with pytest.raises(IngestionError) as captured:
        service.land_symbol(
            dataset="margin_short",
            symbol="2330",
            start_date=date(2021, 7, 19),
            end_date=date(2026, 7, 17),
            scheduled_market="TPEX",
            asset_type="COMMON_STOCK",
            backfill_task_id=8,
        )
    assert captured.value.reason_code == "HISTORICAL_SUPPLEMENTAL_SCOPE_INVALID"
