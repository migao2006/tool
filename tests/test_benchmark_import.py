from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.data.ingestion.benchmark_import import BenchmarkImporter
from src.data.ingestion.contracts import IngestionError
from src.data.providers.settings import ApiProviderSettings
from tests.support.benchmark_fixtures import (
    FakeProvider,
    FakeWriter,
    import_payloads,
    provider_payload,
)


SNAPSHOT_DATE = date(2026, 7, 18)


def registry() -> dict[str, FakeProvider]:
    return {
        provider: FakeProvider(datasets)
        for provider, datasets in import_payloads().items()
    }


def test_importer_dry_run_fetches_both_market_indexes_without_writes() -> None:
    providers = registry()
    writer = FakeWriter()

    summary = BenchmarkImporter(
        settings=ApiProviderSettings(), registry=providers, writer=writer
    ).run(snapshot_date=SNAPSHOT_DATE, dry_run=True)

    assert writer.calls == []
    assert providers["TWSE"].calls == ["return_index"]
    assert providers["TPEX"].calls == ["return_index"]
    assert summary.normalized_records == {
        "benchmark_definitions": 2,
        "market_observations": 4,
    }
    assert summary.database_counts == {}
    assert summary.system_status == "RESEARCH_ONLY"
    assert "LABEL_TARGET_ONLY" in summary.reason_codes
    assert "NOT_EXECUTION_PATH_ALIGNED" in summary.reason_codes


def test_importer_writes_sources_definitions_then_market_observations() -> None:
    writer = FakeWriter()
    summary = BenchmarkImporter(
        settings=ApiProviderSettings(), registry=registry(), writer=writer
    ).run(snapshot_date=SNAPSHOT_DATE)
    upserts = [call for call in writer.calls if call["operation"] == "upsert"]

    assert [call["table"] for call in upserts] == [
        "data_sources",
        "benchmark_definitions",
        "market_observations",
    ]
    definitions_call = upserts[1]
    assert definitions_call["on_conflict"] == "benchmark_code,benchmark_version"
    assert definitions_call["preserve_existing"] is True
    definitions = definitions_call["rows"]
    assert {(row["benchmark_code"], row["market"]) for row in definitions} == {
        ("TWSE_TOTAL_RETURN_INDEX", "TWSE"),
        ("TPEX_TOTAL_RETURN_INDEX", "TPEX"),
    }
    assert {row["benchmark_version"] for row in definitions} == {
        "official-total-return-close-v1"
    }
    assert {row["index_symbol"] for row in definitions} == {
        "TWSE_TOTAL_RETURN_INDEX",
        "TPEX_TOTAL_RETURN_INDEX",
    }
    assert {row["effective_from"] for row in definitions} == {"2026-07-16"}
    assert {row["effective_to"] for row in definitions} == {None}
    assert {row["return_basis"] for row in definitions} == {
        "TOTAL_RETURN_INDEX"
    }
    assert {row["return_convention"] for row in definitions} == {
        "CLOSE_TO_CLOSE"
    }
    assert {row["target_trade_path"] for row in definitions} == {
        "T_PLUS_1_OPEN_TO_H_CLOSE"
    }
    assert {row["alignment_status"] for row in definitions} == {
        "RESEARCH_ONLY"
    }

    observations_call = upserts[2]
    assert observations_call["on_conflict"] == (
        "series_code,observation_at,source_id,source_revision_hash"
    )
    assert observations_call["preserve_existing"] is True
    source_ids = {
        row["source_code"]: index * 10
        for index, row in enumerate(upserts[0]["rows"], start=1)
        if row["source_code"] in {"TWSE", "TPEX"}
    }
    assert {
        (row["series_code"], row["source_id"]) for row in observations_call["rows"]
    } == {
        ("TWSE_TOTAL_RETURN_INDEX", source_ids["TWSE"]),
        ("TPEX_TOTAL_RETURN_INDEX", source_ids["TPEX"]),
    }
    assert {row["benchmark_id"] for row in observations_call["rows"]} == {
        100,
        200,
    }
    assert summary.database_counts == {
        "data_sources": 123,
        "benchmark_definitions": 123,
        "market_observations": 123,
    }


def test_importer_fails_before_observations_when_definition_ids_are_incomplete() -> (
    None
):
    writer = FakeWriter(omit_definition="TPEX_TOTAL_RETURN_INDEX")

    with pytest.raises(IngestionError) as captured:
        BenchmarkImporter(
            settings=ApiProviderSettings(), registry=registry(), writer=writer
        ).run(snapshot_date=SNAPSHOT_DATE)

    assert captured.value.reason_code == "BENCHMARK_DEFINITION_UPSERT_INCOMPLETE"
    assert [
        call["table"] for call in writer.calls if call["operation"] == "upsert"
    ] == [
        "data_sources",
        "benchmark_definitions",
    ]


def test_importer_fails_before_definitions_when_source_ids_are_incomplete() -> None:
    writer = FakeWriter(omit_source="TPEX")

    with pytest.raises(IngestionError) as captured:
        BenchmarkImporter(
            settings=ApiProviderSettings(), registry=registry(), writer=writer
        ).run(snapshot_date=SNAPSHOT_DATE)

    assert captured.value.reason_code == "DATA_SOURCE_UPSERT_INCOMPLETE"
    assert [
        call["table"] for call in writer.calls if call["operation"] == "upsert"
    ] == ["data_sources"]


def test_importer_keeps_retrieval_date_mismatch_visible_and_blocks_write() -> None:
    providers = registry()
    providers["TWSE"].payloads["return_index"] = provider_payload(
        "TWSE",
        "return_index",
        [{"Date": "1150717", "TAIEXTotalReturnIndex": "53,441.21"}],
        retrieved_at=datetime(2026, 7, 17, 6, 0, tzinfo=timezone.utc),
    )
    writer = FakeWriter()
    importer = BenchmarkImporter(
        settings=ApiProviderSettings(), registry=providers, writer=writer
    )

    summary = importer.run(snapshot_date=SNAPSHOT_DATE, dry_run=True)
    assert "SNAPSHOT_DATE_DOES_NOT_MATCH_RETRIEVAL_DATE" in summary.reason_codes

    with pytest.raises(IngestionError) as captured:
        importer.run(snapshot_date=SNAPSHOT_DATE)

    assert captured.value.reason_code == "BENCHMARK_SNAPSHOT_DATE_INVALID"
    assert writer.calls == []
