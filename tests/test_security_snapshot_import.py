from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.security_snapshot_import import SecuritySnapshotImporter
from src.data.providers.contracts import ProviderPayload
from src.data.providers.settings import ApiProviderSettings
from tests.support.security_snapshot_fixtures import import_payloads


SNAPSHOT_DATE = date(2026, 7, 18)


class FakeProvider:
    def __init__(self, payloads: Mapping[str, ProviderPayload]) -> None:
        self.payloads = dict(payloads)
        self.calls: list[str] = []

    def fetch(self, dataset: str) -> ProviderPayload:
        self.calls.append(dataset)
        return self.payloads[dataset]


class FakeWriter:
    def __init__(self, *, omit_source: str | None = None) -> None:
        self.omit_source = omit_source
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
        materialized = [dict(row) for row in rows]
        self.calls.append(
            {
                "operation": "upsert",
                "table": table,
                "rows": materialized,
                "on_conflict": on_conflict,
                "select": select,
                "return_rows": return_rows,
                "preserve_existing": preserve_existing,
            }
        )
        if table == "data_sources":
            return [
                {"source_id": index, "source_code": row["source_code"]}
                for index, row in enumerate(materialized, start=1)
                if row["source_code"] != self.omit_source
            ]
        if table == "securities":
            return [
                {
                    "security_id": index,
                    "market": row["market"],
                    "symbol": row["symbol"],
                }
                for index, row in enumerate(materialized, start=1)
            ]
        return []

    def count_rows(self, table: str) -> int:
        self.calls.append({"operation": "count", "table": table})
        return 123

    def refresh_home_data_status(self) -> None:
        self.refresh_calls += 1


def registry() -> dict[str, FakeProvider]:
    payloads = import_payloads()
    return {
        provider: FakeProvider(datasets)
        for provider, datasets in payloads.items()
    }


def test_snapshot_importer_dry_run_fetches_all_sources_without_writing() -> None:
    providers = registry()
    writer = FakeWriter()
    summary = SecuritySnapshotImporter(
        settings=ApiProviderSettings(), registry=providers, writer=writer
    ).run(snapshot_date=SNAPSHOT_DATE, dry_run=True)

    assert writer.calls == []
    assert writer.refresh_calls == 0
    assert providers["MOPS"].calls == [
        "listed_company_profile",
        "otc_company_profile",
    ]
    assert providers["TWSE"].calls == [
        "changed_trading",
        "suspended",
        "attention",
        "disposals",
    ]
    assert providers["TPEX"].calls == [
        "trading_restrictions",
        "suspended_history",
        "attention",
        "disposals",
    ]
    assert summary.normalized_records["securities"] == 1_000
    assert summary.normalized_records["security_history"] == 1_000
    assert summary.database_counts == {}
    assert summary.system_status == "RESEARCH_ONLY"
    assert "FULL_CASH_DELIVERY_SOURCE_NOT_VERIFIED" in summary.reason_codes
    assert summary.to_dict()["latest_available_at"].endswith("+00:00")


def test_snapshot_importer_writes_sources_securities_then_history() -> None:
    writer = FakeWriter()
    summary = SecuritySnapshotImporter(
        settings=ApiProviderSettings(), registry=registry(), writer=writer
    ).run(snapshot_date=SNAPSHOT_DATE)
    upserts = [call for call in writer.calls if call["operation"] == "upsert"]

    assert [call["table"] for call in upserts] == [
        "data_sources",
        "securities",
        "security_history",
    ]
    history_call = upserts[2]
    assert history_call["on_conflict"] == (
        "security_id,effective_from,source_id,source_version"
    )
    assert history_call["preserve_existing"] is True
    assert len(history_call["rows"]) == 1_000
    assert {row["full_cash_delivery_flag"] for row in history_call["rows"]} == {
        None
    }
    assert {
        row["record_kind"] for row in history_call["rows"]
    } == {"CURRENT_DAILY_SNAPSHOT"}
    assert summary.database_counts == {
        "data_sources": 123,
        "securities": 123,
        "security_history": 123,
    }
    assert writer.refresh_calls == 1


def test_incomplete_source_upsert_fails_before_security_write() -> None:
    writer = FakeWriter(omit_source="TPEX_MOPS_SNAPSHOT")
    importer = SecuritySnapshotImporter(
        settings=ApiProviderSettings(), registry=registry(), writer=writer
    )

    with pytest.raises(IngestionError) as captured:
        importer.run(snapshot_date=SNAPSHOT_DATE)

    assert captured.value.reason_code == "DATA_SOURCE_UPSERT_INCOMPLETE"
    assert [call["table"] for call in writer.calls] == ["data_sources"]


def test_low_market_coverage_fails_before_first_write() -> None:
    payloads = import_payloads(profile_count=499)
    providers = {
        provider: FakeProvider(datasets)
        for provider, datasets in payloads.items()
    }
    writer = FakeWriter()
    importer = SecuritySnapshotImporter(
        settings=ApiProviderSettings(), registry=providers, writer=writer
    )

    with pytest.raises(IngestionError) as captured:
        importer.run(snapshot_date=SNAPSHOT_DATE)

    assert captured.value.reason_code == "SECURITY_MASTER_COVERAGE_TOO_LOW"
    assert writer.calls == []


def test_non_session_snapshot_can_be_diagnosed_but_not_written() -> None:
    payloads = import_payloads(listed_profile_date="1150717")
    providers = {
        provider: FakeProvider(datasets)
        for provider, datasets in payloads.items()
    }
    writer = FakeWriter()
    importer = SecuritySnapshotImporter(
        settings=ApiProviderSettings(), registry=providers, writer=writer
    )

    dry_run = importer.run(snapshot_date=SNAPSHOT_DATE, dry_run=True)
    assert "SNAPSHOT_DATE_NOT_CONFIRMED_BY_BOTH_MARKETS" in dry_run.reason_codes
    with pytest.raises(IngestionError) as captured:
        importer.run(snapshot_date=SNAPSHOT_DATE)

    assert captured.value.reason_code == "SECURITY_SNAPSHOT_NOT_TRADING_DAY"
    assert writer.calls == []
