from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json
from typing import Any

import pytest

from src.data.ingestion import calendar_import
from src.data.ingestion.calendar_import import TradingCalendarImporter
from src.data.ingestion.calendar_observations import (
    DATE_ONLY_REASON_CODES,
    normalize_finmind_calendar_observations,
)
from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.trading_calendar import normalize_finmind_trading_calendar
from src.data.providers.contracts import ProviderPayload
from src.data.providers.settings import ApiProviderSettings


RETRIEVED_AT = datetime(2026, 7, 18, 6, 0, tzinfo=timezone.utc)


def calendar_payload(dates: list[str]) -> ProviderPayload:
    raw: dict[str, Any] = {
        "status": 200,
        "data": [{"date": value} for value in dates],
    }
    digest = sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return ProviderPayload(
        provider="FINMIND",
        dataset="trading_calendar",
        source_version="api.v4",
        source_url=(
            "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockTradingDate"
        ),
        retrieved_at=RETRIEVED_AT,
        payload_sha256=digest,
        payload=raw,
    )


class FakeFinMind:
    def __init__(self, payload: ProviderPayload) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def fetch(self, dataset: str, **kwargs: object) -> ProviderPayload:
        self.calls.append({"dataset": dataset, **kwargs})
        return self.payload


class FakeWriter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.refresh_calls = 0

    def upsert(
        self,
        table: str,
        rows,
        *,
        on_conflict: str,
        select: str | None = None,
        return_rows: bool = False,
        preserve_existing: bool = False,
    ) -> list[dict[str, object]]:
        self.calls.append(
            {
                "table": table,
                "rows": list(rows),
                "on_conflict": on_conflict,
                "select": select,
                "return_rows": return_rows,
                "preserve_existing": preserve_existing,
            }
        )
        if table == "data_sources":
            return [{"source_id": 77, "source_code": "FINMIND"}]
        return []

    def count_rows(self, table: str) -> int:
        self.calls.append({"table": table, "operation": "count"})
        return 1_234

    def refresh_home_data_status(self) -> None:
        self.refresh_calls += 1


def test_calendar_normalizer_sorts_actual_sessions_without_inventing_times() -> None:
    rows = normalize_finmind_trading_calendar(
        calendar_payload(["2026-01-06", "2026-01-05", "2026-01-07"]),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 10),
        source_id=7,
    )

    assert [row["trading_date"] for row in rows] == [
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
    ]
    assert {row["market"] for row in rows} == {"TWSE"}
    assert {row["available_at"] for row in rows} == {RETRIEVED_AT.isoformat()}
    assert all(row["opens_at"] is None for row in rows)
    assert all(row["closes_at"] is None for row in rows)
    assert all(row["decision_data_cutoff_at"] is None for row in rows)


def test_calendar_normalizer_refuses_unverified_tpex_mapping() -> None:
    with pytest.raises(IngestionError) as captured:
        normalize_finmind_trading_calendar(
            calendar_payload(["2026-01-05"]),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 10),
            source_id=7,
            markets=("TPEX",),
        )
    assert captured.value.reason_code == "TRADING_CALENDAR_MARKET_NOT_VERIFIED"


def test_calendar_normalizer_accepts_exchange_confirmed_saturday_sessions() -> None:
    rows = normalize_finmind_trading_calendar(
        calendar_payload(["2018-03-30", "2018-03-31"]),
        start_date=date(2018, 3, 30),
        end_date=date(2018, 4, 1),
        source_id=7,
    )

    assert [row["trading_date"] for row in rows] == ["2018-03-30", "2018-03-31"]


@pytest.mark.parametrize(
    ("dates", "start_date", "end_date", "reason_code"),
    [
        (
            ["2026-01-05", "2026-01-05"],
            date(2026, 1, 1),
            date(2026, 1, 10),
            "TRADING_CALENDAR_DUPLICATE_DATE",
        ),
        (
            ["2025-12-31", "2026-01-05"],
            date(2026, 1, 1),
            date(2026, 1, 10),
            "TRADING_CALENDAR_DATE_OUT_OF_RANGE",
        ),
        (
            ["2026-07-20"],
            date(2026, 7, 19),
            date(2026, 7, 21),
            "TRADING_CALENDAR_FUTURE_RANGE",
        ),
    ],
)
def test_calendar_normalizer_rejects_invalid_sessions(
    dates: list[str],
    start_date: date,
    end_date: date,
    reason_code: str,
) -> None:
    with pytest.raises(IngestionError) as captured:
        normalize_finmind_trading_calendar(
            calendar_payload(dates),
            start_date=start_date,
            end_date=end_date,
            source_id=7,
        )
    assert captured.value.reason_code == reason_code


def test_calendar_normalizer_rejects_truncated_long_range() -> None:
    with pytest.raises(IngestionError) as captured:
        normalize_finmind_trading_calendar(
            calendar_payload(["2026-01-05", "2026-06-30"]),
            start_date=date(2026, 1, 1),
            end_date=date(2026, 6, 30),
            source_id=7,
        )
    assert captured.value.reason_code == "TRADING_CALENDAR_COVERAGE_INCOMPLETE"


def test_calendar_importer_dry_run_does_not_touch_supabase() -> None:
    provider = FakeFinMind(calendar_payload(["2026-01-05", "2026-01-06", "2026-01-07"]))
    writer = FakeWriter()
    summary = TradingCalendarImporter(
        settings=ApiProviderSettings(finmind_token="secret"),
        registry={"FINMIND": provider},
        writer=writer,
    ).run(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 10),
        dry_run=True,
    )

    assert writer.calls == []
    assert writer.refresh_calls == 0
    assert provider.calls == [
        {
            "dataset": "trading_calendar",
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 1, 10),
        }
    ]
    assert summary.database_count is None
    assert summary.system_status == "RESEARCH_ONLY"
    assert summary.status == "PASS"
    assert "HISTORICAL_RANGE_BELOW_SEVEN_YEARS" in summary.reason_codes
    assert set(DATE_ONLY_REASON_CODES).issubset(summary.reason_codes)
    assert summary.source_hash == provider.payload.payload_sha256


def test_calendar_importer_dry_run_validates_observation_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail(*_: object, **__: object):
        raise IngestionError(
            "OBSERVATION_CONTRACT_REJECTED",
            "test-only observation rejection",
        )

    monkeypatch.setattr(
        calendar_import,
        "normalize_finmind_calendar_observations",
        _fail,
    )
    importer = TradingCalendarImporter(
        settings=ApiProviderSettings(finmind_token="secret"),
        registry={"FINMIND": FakeFinMind(calendar_payload(["2026-01-05"]))},
        writer=FakeWriter(),
    )

    with pytest.raises(IngestionError) as captured:
        _ = importer.run(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 10),
            dry_run=True,
        )

    assert captured.value.reason_code == "OBSERVATION_CONTRACT_REJECTED"


def test_calendar_importer_writes_source_then_idempotent_calendar_rows() -> None:
    provider = FakeFinMind(calendar_payload(["2026-01-05", "2026-01-06", "2026-01-07"]))
    writer = FakeWriter()
    summary = TradingCalendarImporter(
        settings=ApiProviderSettings(finmind_token="secret"),
        registry={"FINMIND": provider},
        writer=writer,
    ).run(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 10),
    )

    assert [call["table"] for call in writer.calls] == [
        "data_sources",
        "trading_calendar",
        "trading_calendar_observations",
        "trading_calendar",
        "trading_calendar_observations",
    ]
    calendar_call = writer.calls[1]
    assert calendar_call["on_conflict"] == "market,trading_date"
    assert calendar_call["preserve_existing"] is True
    assert {row["source_id"] for row in calendar_call["rows"]} == {77}
    observation_call = writer.calls[2]
    assert observation_call["on_conflict"] == (
        "source_id,source_dataset,source_event_id,market,trading_date,"
        "source_revision_hash"
    )
    assert observation_call["preserve_existing"] is True
    assert {row["calendar_verification_status"] for row in observation_call["rows"]} == {
        "UNRESOLVED"
    }
    assert {row["market_basis"] for row in observation_call["rows"]} == {
        "SCHEDULING_HINT"
    }
    assert all(row["opens_at"] is None for row in observation_call["rows"])
    assert summary.database_count == 1_234
    assert summary.observation_database_count == 1_234
    assert summary.normalized_records == 3
    assert summary.to_dict()["retrieved_at"] == RETRIEVED_AT.isoformat()
    assert writer.refresh_calls == 1


def test_calendar_observations_preserve_exact_row_lineage_and_hashes() -> None:
    payload = calendar_payload(["2026-01-05", "2026-01-06"])
    sessions = normalize_finmind_trading_calendar(
        payload,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 10),
        source_id=77,
    )

    first = normalize_finmind_calendar_observations(
        payload, sessions, source_id=77
    )
    second = normalize_finmind_calendar_observations(
        payload, sessions, source_id=77
    )

    assert first == second
    assert [row["source_row"] for row in first] == [
        {"date": "2026-01-05"},
        {"date": "2026-01-06"},
    ]
    assert all(len(str(row["source_revision_hash"])) == 64 for row in first)
    assert {row["source_payload_hash"] for row in first} == {
        payload.payload_sha256
    }
    assert {row["available_at"] for row in first} == {
        RETRIEVED_AT.isoformat()
    }
    assert {row["usage_scope"] for row in first} == {
        "CALENDAR_RESEARCH_ONLY"
    }
    assert all(set(row["reason_codes"]) == set(DATE_ONLY_REASON_CODES) for row in first)
