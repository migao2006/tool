from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.finmind_historical_evidence_import import (
    FinMindHistoricalEvidenceImporter,
)
from src.data.providers.settings import ApiProviderSettings
from tests.support.finmind_historical_evidence_fixtures import (
    FakeProvider,
    FakeWriter,
    identity,
    payload,
)


START = date(2000, 1, 1)
END = date(2026, 7, 19)


def test_dry_run_fetches_all_evidence_without_database_access() -> None:
    provider = FakeProvider()
    writer = FakeWriter()

    summary = FinMindHistoricalEvidenceImporter(
        settings=ApiProviderSettings(), provider=provider, writer=writer
    ).run(
        symbols=("2330",),
        start_date=START,
        end_date=END,
        pacing_seconds=0,
        dry_run=True,
        identities=(identity(),),
    )

    assert provider.calls == [
        ("api_quota", None),
        ("dividend_results", "2330"),
        ("stock_splits", None),
        ("par_value_changes", None),
        ("suspended", None),
    ]
    assert writer.calls == []
    assert summary.status == "RESEARCH_ONLY"
    assert summary.import_scope == "ALL"
    assert summary.fetched_records == {
        "dividend_results": 1,
        "stock_splits": 2,
        "par_value_changes": 1,
        "suspended": 1,
    }
    assert summary.normalized_action_rows == 3
    assert summary.canonical_state_event_rows == 1
    assert summary.verified_identity_rows == 4
    assert summary.action_rows_submitted == 0
    assert summary.state_event_rows_persisted == 0
    assert len(summary.source_retrieved_at) == 4
    assert "SECURITY_STATE_PERSISTENCE_CONTRACT_NOT_CONFIGURED" in (
        summary.reason_codes
    )


def test_import_loads_identity_then_appends_only_action_evidence() -> None:
    provider = FakeProvider()
    writer = FakeWriter()

    summary = FinMindHistoricalEvidenceImporter(
        settings=ApiProviderSettings(), provider=provider, writer=writer
    ).run(
        symbols=("2330",),
        start_date=START,
        end_date=END,
        pacing_seconds=0,
    )

    assert [call["operation"] for call in writer.calls] == [
        "select",
        "upsert",
        "upsert",
        "count",
    ]
    assert [
        call.get("table") for call in writer.calls if call["operation"] == "upsert"
    ] == ["data_sources", "historical_corporate_action_observations"]
    action_call = writer.calls[2]
    assert action_call["preserve_existing"] is True
    assert action_call["on_conflict"] == (
        "source_id,source_dataset,source_event_id,action_type,source_revision_hash"
    )
    action_rows = action_call["rows"]
    assert isinstance(action_rows, list)
    assert all(row["source_id"] == 42 for row in action_rows)
    assert all(
        row["usage_scope"] == "ACTION_RESEARCH_ONLY"
        and row["system_status"] == "RESEARCH_ONLY"
        for row in action_rows
    )
    assert not any(
        call.get("table") == "security_state_snapshots" for call in writer.calls
    )
    assert summary.action_rows_submitted == 3
    assert summary.state_event_rows_persisted == 0
    assert summary.database_counts == {"historical_corporate_action_observations": 77}


def test_quota_failure_happens_before_fetch_or_database_access() -> None:
    provider = FakeProvider(remaining=3)
    writer = FakeWriter()
    importer = FinMindHistoricalEvidenceImporter(
        settings=ApiProviderSettings(), provider=provider, writer=writer
    )

    with pytest.raises(IngestionError) as captured:
        importer.run(
            symbols=("2330",),
            start_date=START,
            end_date=END,
            pacing_seconds=0,
        )

    assert captured.value.reason_code == "FINMIND_HISTORICAL_QUOTA_INSUFFICIENT"
    assert provider.calls == [("api_quota", None)]
    assert writer.calls == []


def test_missing_finmind_source_id_blocks_action_write() -> None:
    writer = FakeWriter(return_source=False)
    importer = FinMindHistoricalEvidenceImporter(
        settings=ApiProviderSettings(), provider=FakeProvider(), writer=writer
    )

    with pytest.raises(IngestionError) as captured:
        importer.run(
            symbols=("2330",),
            start_date=START,
            end_date=END,
            pacing_seconds=0,
            identities=(identity(),),
        )

    assert captured.value.reason_code == "DATA_SOURCE_UPSERT_INCOMPLETE"
    assert [call.get("table") for call in writer.calls] == ["data_sources"]


def test_dividend_scope_never_fetches_global_datasets() -> None:
    provider = FakeProvider()

    summary = FinMindHistoricalEvidenceImporter(
        settings=ApiProviderSettings(), provider=provider, writer=FakeWriter()
    ).run(
        symbols=("2330",),
        start_date=START,
        end_date=END,
        pacing_seconds=0,
        scope="DIVIDENDS",
        dry_run=True,
        identities=(identity(),),
    )

    assert provider.calls == [
        ("api_quota", None),
        ("dividend_results", "2330"),
    ]
    assert summary.import_scope == "DIVIDENDS"
    assert summary.canonical_state_event_rows == 0


def test_global_scope_fetches_each_global_dataset_once() -> None:
    provider = FakeProvider()

    summary = FinMindHistoricalEvidenceImporter(
        settings=ApiProviderSettings(), provider=provider, writer=FakeWriter()
    ).run(
        symbols=("2330",),
        start_date=START,
        end_date=END,
        pacing_seconds=0,
        scope="GLOBAL",
        dry_run=True,
        identities=(identity(),),
    )

    assert provider.calls == [
        ("api_quota", None),
        ("stock_splits", None),
        ("par_value_changes", None),
        ("suspended", None),
    ]
    assert summary.import_scope == "GLOBAL"
    assert summary.canonical_state_event_rows == 1


def test_quota_reserve_is_kept_before_any_evidence_request() -> None:
    provider = FakeProvider(remaining=4)

    with pytest.raises(IngestionError) as captured:
        FinMindHistoricalEvidenceImporter(
            settings=ApiProviderSettings(), provider=provider, writer=FakeWriter()
        ).run(
            symbols=("2330",),
            start_date=START,
            end_date=END,
            pacing_seconds=0,
            scope="DIVIDENDS",
            quota_reserve=4,
            dry_run=True,
            identities=(identity(),),
        )

    assert captured.value.reason_code == "FINMIND_HISTORICAL_QUOTA_INSUFFICIENT"
    assert provider.calls == [("api_quota", None)]


def test_primary_batch_filters_global_payload_against_full_identity_catalog() -> None:
    provider = FakeProvider()
    provider.by_dataset["stock_splits"] = payload(
        "stock_splits",
        [
            {
                "date": "2020-07-01",
                "stock_id": symbol,
                "type": "split",
                "before_price": 100,
                "after_price": 50,
            }
            for symbol in ("2330", "2317")
        ],
    )
    second_identity = replace(
        identity(),
        listing_evidence_id=12,
        listing_period_id="TWSE:2317:2000-01-01",
        security_id=102,
        source_symbol="2317",
    )

    summary = FinMindHistoricalEvidenceImporter(
        settings=ApiProviderSettings(), provider=provider, writer=FakeWriter()
    ).run(
        symbols=("2330",),
        global_symbols=("2317", "2330"),
        start_date=START,
        end_date=END,
        pacing_seconds=0,
        scope="ALL",
        dry_run=True,
        identities=(identity(), second_identity),
    )

    assert summary.requested_symbols == ("2330",)
    assert summary.requested_global_symbols == ("2317", "2330")
    assert summary.normalized_action_rows == 4
