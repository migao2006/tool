from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from hashlib import sha256
import json

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.historical_daily_bar_import import HistoricalDailyBarImporter
from src.data.providers.contracts import ProviderPayload
from src.data.providers.settings import ApiProviderSettings


def _payload(dataset: str, body: object) -> ProviderPayload:
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return ProviderPayload(
        provider="FINMIND",
        dataset=dataset,
        source_version="api.v4",
        source_url="https://api.finmindtrade.com/api/v4/data",
        retrieved_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
        payload_sha256=sha256(encoded).hexdigest(),
        payload=body,
    )


def _bar(symbol: str, *, open_price: object = 100) -> dict[str, object]:
    return {
        "date": "2026-07-17",
        "stock_id": symbol,
        "Trading_Volume": 1_000_000,
        "Trading_money": 100_000_000,
        "open": open_price,
        "max": 102,
        "min": 99,
        "close": 101,
        "Trading_turnover": 500,
    }


class FakeProvider:
    def __init__(
        self,
        rows: Mapping[str, list[object]],
        *,
        quota_used: int = 10,
        quota_limit: int = 600,
    ) -> None:
        self.rows = rows
        self.quota_used = quota_used
        self.quota_limit = quota_limit
        self.calls: list[str] = []

    def fetch_quota(self) -> ProviderPayload:
        self.calls.append("quota")
        return _payload(
            "api_quota",
            {
                "user_count": self.quota_used,
                "api_request_limit": self.quota_limit,
            },
        )

    def fetch(
        self,
        dataset: str,
        *,
        data_id: str | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> ProviderPayload:
        assert dataset == "daily_bars"
        assert isinstance(data_id, str)
        _ = (start_date, end_date)
        self.calls.append(data_id)
        return _payload("daily_bars", {"status": 200, "data": self.rows[data_id]})


class FakeWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict[str, object]], str]] = []
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
        _ = (select, preserve_existing)
        copied = [dict(row) for row in rows]
        self.calls.append((table, copied, on_conflict))
        if table == "data_sources" and return_rows:
            return [{"source_id": 7, "source_code": "FINMIND"}]
        return []

    def count_rows(self, table: str) -> int:
        return {
            "historical_daily_bar_landing": 2,
            "historical_daily_bar_quarantine": 0,
        }[table]

    def refresh_home_data_status(self) -> None:
        self.refresh_calls += 1


def _settings() -> ApiProviderSettings:
    return ApiProviderSettings()


def test_dry_run_fetches_and_normalizes_without_constructing_writer() -> None:
    provider = FakeProvider({"2330": [_bar("2330")]})
    summary = HistoricalDailyBarImporter(
        settings=_settings(),
        provider=provider,
        sleep_fn=lambda _: None,
    ).run(
        symbols=("2330",),
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 17),
        pacing_seconds=0,
        dry_run=True,
    )

    assert provider.calls == ["quota", "2330"]
    assert summary.fetched_rows == summary.landed_rows == 1
    assert summary.quarantined_rows == summary.quarantine_issues == 0
    assert summary.database_counts == {}
    assert summary.status == "RESEARCH_ONLY"


def test_formal_import_only_writes_source_and_isolated_landing_tables() -> None:
    provider = FakeProvider({"2330": [_bar("2330")], "2317": [_bar("2317")]})
    writer = FakeWriter()
    sleeps: list[float] = []

    summary = HistoricalDailyBarImporter(
        settings=_settings(),
        provider=provider,
        writer=writer,
        sleep_fn=sleeps.append,
    ).run(
        symbols=("2330", "2317"),
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 17),
        pacing_seconds=7.5,
    )

    assert sleeps == [7.5]
    assert summary.landed_rows == 2
    tables = [table for table, _, _ in writer.calls]
    assert set(tables) == {"data_sources", "historical_daily_bar_landing"}
    assert not {"securities", "security_history", "daily_bars"} & set(tables)
    landing_rows = [
        row
        for table, rows, _ in writer.calls
        if table == "historical_daily_bar_landing"
        for row in rows
    ]
    assert all(row["source_id"] == 7 for row in landing_rows)
    assert all(
        "source_code" not in row and "security_id" not in row for row in landing_rows
    )
    assert writer.refresh_calls == 1


def test_invalid_source_row_lands_before_quarantine_issue() -> None:
    writer = FakeWriter()
    summary = HistoricalDailyBarImporter(
        settings=_settings(),
        provider=FakeProvider({"2330": [_bar("2330", open_price="bad")]}),
        writer=writer,
        sleep_fn=lambda _: None,
    ).run(
        symbols=("2330",),
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 17),
        pacing_seconds=0,
    )

    tables = [table for table, _, _ in writer.calls]
    assert tables.index("historical_daily_bar_landing") < tables.index(
        "historical_daily_bar_quarantine"
    )
    assert summary.quarantined_rows == 1
    assert summary.quarantine_issues >= 1


def test_empty_symbol_response_fails_before_any_landing_write() -> None:
    writer = FakeWriter()
    importer = HistoricalDailyBarImporter(
        settings=_settings(),
        provider=FakeProvider({"2330": []}),
        writer=writer,
        sleep_fn=lambda _: None,
    )

    with pytest.raises(IngestionError) as captured:
        importer.run(
            symbols=("2330",),
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 17),
            pacing_seconds=0,
        )

    assert captured.value.reason_code == "HISTORICAL_DAILY_BAR_EMPTY_RESPONSE"
    assert writer.calls == []


def test_insufficient_quota_fails_before_fetch_or_write() -> None:
    provider = FakeProvider({"2330": [_bar("2330")]}, quota_used=600)
    writer = FakeWriter()

    with pytest.raises(IngestionError) as captured:
        HistoricalDailyBarImporter(
            settings=_settings(),
            provider=provider,
            writer=writer,
            sleep_fn=lambda _: None,
        ).run(
            symbols=("2330",),
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 17),
            pacing_seconds=0,
        )

    assert captured.value.reason_code == "FINMIND_IMPORT_QUOTA_INSUFFICIENT"
    assert provider.calls == ["quota"]
    assert writer.calls == []
