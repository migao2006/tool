from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import cast

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.delisting_registry_import import DelistingRegistryImporter
from src.data.providers.settings import ApiProviderSettings
from tests.support.delisting_registry_fixtures import (
    FakeProvider,
    FakeWriter,
    import_payloads,
    twse_payload,
)


SNAPSHOT_DATE = date(2026, 7, 18)


def registry() -> dict[str, FakeProvider]:
    return {
        provider: FakeProvider(datasets)
        for provider, datasets in import_payloads().items()
    }


def test_dry_run_fetches_both_official_registries_without_writes() -> None:
    providers = registry()
    writer = FakeWriter()

    summary = DelistingRegistryImporter(
        settings=ApiProviderSettings(),
        registry=providers,
        writer=writer,
    ).run(snapshot_date=SNAPSHOT_DATE, dry_run=True)

    assert writer.calls == []
    assert writer.refresh_calls == 0
    assert providers["TWSE"].calls == ["delisting_registry"]
    assert providers["TPEX"].calls == ["delisting_registry"]
    assert summary.normalized_records == {"TWSE": 200, "TPEX": 500}
    assert summary.system_status == "RESEARCH_ONLY"
    assert "HISTORICAL_IDENTITY_REGISTRY_ONLY" in summary.reason_codes


def test_formal_import_writes_only_sources_then_unresolved_registry() -> None:
    writer = FakeWriter()

    summary = DelistingRegistryImporter(
        settings=ApiProviderSettings(),
        registry=registry(),
        writer=writer,
    ).run(snapshot_date=SNAPSHOT_DATE)

    upserts = [call for call in writer.calls if "on_conflict" in call]
    assert [call["table"] for call in upserts] == [
        "data_sources",
        "delisting_registry_observations",
    ]
    assert not {"securities", "security_history"} & {
        str(call["table"]) for call in writer.calls
    }
    registry_call = upserts[1]
    registry_rows = registry_call["rows"]
    assert isinstance(registry_rows, list)
    typed_registry_rows = cast(list[object], registry_rows)
    assert len(typed_registry_rows) == 700
    assert registry_call["preserve_existing"] is True
    assert registry_call["on_conflict"] == (
        "source_id,source_dataset,source_event_id,source_revision_hash"
    )
    assert all(
        isinstance(row, Mapping) and "security_id" not in row
        for row in typed_registry_rows
    )
    assert summary.database_counts == {
        "data_sources": 123,
        "delisting_registry_observations": 123,
    }
    assert writer.refresh_calls == 1


def test_missing_source_id_blocks_registry_write() -> None:
    writer = FakeWriter(omit_source="TPEX")

    with pytest.raises(IngestionError) as captured:
        _ = DelistingRegistryImporter(
            settings=ApiProviderSettings(),
            registry=registry(),
            writer=writer,
        ).run(snapshot_date=SNAPSHOT_DATE)

    assert captured.value.reason_code == "DATA_SOURCE_UPSERT_INCOMPLETE"
    assert [call["table"] for call in writer.calls] == ["data_sources"]


def test_retrieval_date_mismatch_is_visible_and_blocks_formal_write() -> None:
    providers = registry()
    rows_value = cast(object, import_payloads()["TWSE"]["delisting_registry"].payload)
    assert isinstance(rows_value, list)
    typed_rows = cast(list[object], rows_value)
    assert all(isinstance(row, dict) for row in typed_rows)
    rows = cast(list[dict[str, object]], typed_rows)
    providers["TWSE"].payloads["delisting_registry"] = twse_payload(
        rows,
        retrieved_at=datetime(2026, 7, 17, 6, 0, tzinfo=timezone.utc),
    )
    writer = FakeWriter()
    importer = DelistingRegistryImporter(
        settings=ApiProviderSettings(), registry=providers, writer=writer
    )

    summary = importer.run(snapshot_date=SNAPSHOT_DATE, dry_run=True)
    assert "SNAPSHOT_DATE_DOES_NOT_MATCH_RETRIEVAL_DATE" in summary.reason_codes

    with pytest.raises(IngestionError) as captured:
        _ = importer.run(snapshot_date=SNAPSHOT_DATE)

    assert captured.value.reason_code == "DELISTING_SNAPSHOT_DATE_INVALID"
    assert writer.calls == []


def test_coverage_floor_blocks_partial_official_snapshot() -> None:
    providers = registry()
    providers["TWSE"].payloads["delisting_registry"] = twse_payload()

    with pytest.raises(IngestionError) as captured:
        _ = DelistingRegistryImporter(
            settings=ApiProviderSettings(),
            registry=providers,
            writer=FakeWriter(),
        ).run(snapshot_date=SNAPSHOT_DATE, dry_run=True)

    assert captured.value.reason_code == "DELISTING_COVERAGE_TOO_LOW"
