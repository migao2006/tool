from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from hashlib import sha256
import json

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.historical_daily_bar_landing_service import (
    HistoricalDailyBarLandingService,
)
from src.data.providers.contracts import ProviderPayload


START_DATE = date(2020, 1, 1)
END_DATE = date(2020, 1, 31)


def _bar(trade_date: str, *, open_price: object = 332.5) -> dict[str, object]:
    return {
        "date": trade_date,
        "stock_id": "2330",
        "Trading_Volume": 34_000_000,
        "Trading_money": 11_500_000_000,
        "open": open_price,
        "max": 339.0,
        "min": 332.5,
        "close": 339.0,
        "Trading_turnover": 30_115,
    }


def _payload(rows: list[object]) -> ProviderPayload:
    body = {"status": 200, "data": rows}
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return ProviderPayload(
        provider="FINMIND",
        dataset="daily_bars",
        source_version="api.v4",
        source_url="https://api.finmindtrade.com/api/v4/data",
        retrieved_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        payload_sha256=sha256(encoded).hexdigest(),
        payload=body,
    )


class FakeProvider:
    def __init__(self, payload: ProviderPayload) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def fetch(
        self,
        dataset: str,
        *,
        data_id: str | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> ProviderPayload:
        self.calls.append(
            {
                "dataset": dataset,
                "data_id": data_id,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
        return self.payload


class RecordingWriter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.refresh_calls = 0

    def upsert(
        self,
        table: str,
        rows: Sequence[Mapping[str, object]],
        *,
        on_conflict: str,
        select: str | None = None,
        return_rows: bool = False,
        preserve_existing: bool = False,
    ) -> list[dict[str, object]]:
        self.calls.append(
            {
                "table": table,
                "rows": [dict(row) for row in rows],
                "on_conflict": on_conflict,
                "preserve_existing": preserve_existing,
            }
        )
        if table == "data_sources" and select and return_rows:
            return [{"source_id": 7, "source_code": "FINMIND"}]
        return []

    def refresh_home_data_status(self) -> None:
        self.refresh_calls += 1


class RecordingArchive:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

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
    ) -> object:
        self.calls.append(
            {
                "rows": [dict(row) for row in rows],
                "quarantine_rows": [dict(row) for row in quarantine_rows],
                "payload": payload,
                "scheduled_market": scheduled_market,
                "asset_type": asset_type,
                "symbol": symbol,
                "start_date": start_date,
                "end_date": end_date,
                "backfill_task_id": backfill_task_id,
            }
        )
        return object()


def test_archive_mode_writes_archive_without_full_landing_or_quarantine_rows() -> None:
    source = _payload([_bar("2020-01-02"), _bar("2020-01-03", open_price="invalid")])
    provider = FakeProvider(source)
    writer = RecordingWriter()
    archive = RecordingArchive()
    service = HistoricalDailyBarLandingService(
        provider=provider,
        writer=writer,
        archive_service=archive,
    )

    result = service.land_symbol(
        symbol="2330",
        start_date=START_DATE,
        end_date=END_DATE,
        scheduled_market="TWSE",
        asset_type="COMMON_STOCK",
        backfill_task_id=41,
    )
    service.refresh_home_status()

    assert result.fetched_rows == result.landed_rows == 2
    assert result.quarantined_rows == 1
    assert len(archive.calls) == 1
    call = archive.calls[0]
    assert call["payload"] is source
    assert call["scheduled_market"] == "TWSE"
    assert call["asset_type"] == "COMMON_STOCK"
    assert call["backfill_task_id"] == 41
    assert len(call["rows"]) == 2
    assert len(call["quarantine_rows"]) >= 1
    assert all("source_id" not in row for row in call["rows"])
    assert writer.calls == []
    assert writer.refresh_calls == 1


def test_without_archive_service_preserves_supabase_landing_behavior() -> None:
    provider = FakeProvider(_payload([_bar("2020-01-02")]))
    writer = RecordingWriter()
    service = HistoricalDailyBarLandingService(provider=provider, writer=writer)

    result = service.land_symbol(
        symbol="2330",
        start_date=START_DATE,
        end_date=END_DATE,
        scheduled_market="TWSE",
        asset_type="COMMON_STOCK",
        backfill_task_id=41,
    )
    service.refresh_home_status()

    assert result.landed_rows == 1
    assert [call["table"] for call in writer.calls] == [
        "data_sources",
        "historical_daily_bar_landing",
    ]
    landing = writer.calls[1]["rows"][0]
    assert landing["source_id"] == 7
    assert "source_code" not in landing
    assert writer.refresh_calls == 1


def test_archive_mode_requires_context_before_fetching() -> None:
    provider = FakeProvider(_payload([_bar("2020-01-02")]))
    archive = RecordingArchive()
    service = HistoricalDailyBarLandingService(
        provider=provider,
        writer=None,
        archive_service=archive,
    )

    with pytest.raises(IngestionError) as captured:
        service.land_symbol(
            symbol="2330",
            start_date=START_DATE,
            end_date=END_DATE,
        )

    assert captured.value.reason_code == "HISTORICAL_ARCHIVE_CONTEXT_MISSING"
    assert provider.calls == []
    assert archive.calls == []
