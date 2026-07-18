from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.corporate_action_import import CorporateActionImporter
from src.data.providers.settings import ApiProviderSettings
from tests.support.corporate_action_fixtures import (
    FakeProvider,
    FakeWriter,
    import_payloads,
    provider_payload,
)


SNAPSHOT_DATE = date(2026, 7, 18)


def registry(profile_count: int = 500) -> dict[str, FakeProvider]:
    return {
        provider: FakeProvider(datasets)
        for provider, datasets in import_payloads(profile_count).items()
    }


def test_importer_dry_run_fetches_all_sources_and_never_writes() -> None:
    providers = registry()
    writer = FakeWriter()

    summary = CorporateActionImporter(
        settings=ApiProviderSettings(), registry=providers, writer=writer
    ).run(snapshot_date=SNAPSHOT_DATE, dry_run=True)

    assert writer.calls == []
    assert writer.refresh_calls == 0
    assert sorted(providers["MOPS"].calls) == [
        "listed_company_profile",
        "otc_company_profile",
    ]
    assert providers["TWSE"].calls == ["ex_rights"]
    assert providers["TPEX"].calls == ["ex_rights_forecast"]
    assert summary.normalized_records["corporate_actions"] == 3
    assert summary.database_counts == {}
    assert summary.system_status == "RESEARCH_ONLY"


def test_importer_writes_sources_securities_then_actions_with_returned_ids() -> None:
    writer = FakeWriter()
    summary = CorporateActionImporter(
        settings=ApiProviderSettings(), registry=registry(), writer=writer
    ).run(snapshot_date=SNAPSHOT_DATE)
    upserts = [call for call in writer.calls if call["operation"] == "upsert"]

    assert [call["table"] for call in upserts] == [
        "data_sources",
        "securities",
        "corporate_actions",
    ]
    actions_call = upserts[2]
    assert actions_call["on_conflict"] == (
        "source_id,source_event_id,source_revision_hash"
    )
    assert actions_call["preserve_existing"] is True
    security_ids = {
        (row["market"], row["symbol"]): index * 100
        for index, row in enumerate(upserts[1]["rows"], start=1)
    }
    source_ids = {
        row["source_code"]: index * 10
        for index, row in enumerate(upserts[0]["rows"], start=1)
    }
    assert {(row["security_id"], row["source_id"]) for row in actions_call["rows"]} == {
        (security_ids[("TWSE", "2330")], source_ids["TWSE"]),
        (security_ids[("TPEX", "6488")], source_ids["TPEX"]),
    }
    assert summary.database_counts == {
        "data_sources": 123,
        "securities": 123,
        "corporate_actions": 123,
    }
    assert writer.refresh_calls == 1


def test_incomplete_source_return_fails_before_security_write() -> None:
    writer = FakeWriter(omit_source="TPEX")
    importer = CorporateActionImporter(
        settings=ApiProviderSettings(), registry=registry(), writer=writer
    )

    with pytest.raises(IngestionError) as captured:
        importer.run(snapshot_date=SNAPSHOT_DATE)

    assert captured.value.reason_code == "DATA_SOURCE_UPSERT_INCOMPLETE"
    assert [call["table"] for call in writer.calls] == ["data_sources"]


def test_incomplete_security_return_fails_before_action_write() -> None:
    writer = FakeWriter(omit_security=("TPEX", "6488"))
    importer = CorporateActionImporter(
        settings=ApiProviderSettings(), registry=registry(), writer=writer
    )

    with pytest.raises(IngestionError) as captured:
        importer.run(snapshot_date=SNAPSHOT_DATE)

    assert captured.value.reason_code == "SECURITY_MASTER_UPSERT_INCOMPLETE"
    assert [call["table"] for call in writer.calls] == [
        "data_sources",
        "securities",
    ]


def test_low_market_coverage_fails_before_any_write() -> None:
    writer = FakeWriter()
    importer = CorporateActionImporter(
        settings=ApiProviderSettings(), registry=registry(profile_count=499), writer=writer
    )

    with pytest.raises(IngestionError) as captured:
        importer.run(snapshot_date=SNAPSHOT_DATE)

    assert captured.value.reason_code == "SECURITY_MASTER_COVERAGE_TOO_LOW"
    assert writer.calls == []


def test_mismatched_retrieval_date_is_visible_in_dry_run_and_blocks_write() -> None:
    providers = registry()
    providers["TWSE"].payloads["ex_rights"] = provider_payload(
        "TWSE",
        "ex_rights",
        [],
        retrieved_at=datetime(2026, 7, 17, 6, 0, tzinfo=timezone.utc),
    )
    writer = FakeWriter()
    importer = CorporateActionImporter(
        settings=ApiProviderSettings(), registry=providers, writer=writer
    )

    summary = importer.run(snapshot_date=SNAPSHOT_DATE, dry_run=True)
    assert "SNAPSHOT_DATE_DOES_NOT_MATCH_RETRIEVAL_DATE" in summary.reason_codes

    with pytest.raises(IngestionError) as captured:
        importer.run(snapshot_date=SNAPSHOT_DATE)

    assert captured.value.reason_code == "CORPORATE_ACTION_SNAPSHOT_DATE_INVALID"
    assert writer.calls == []
