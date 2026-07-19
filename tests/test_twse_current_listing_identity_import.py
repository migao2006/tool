from __future__ import annotations

from datetime import date, datetime, timezone
from typing import cast

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.twse_current_listing_identity_import import (
    TwseCurrentListingIdentityImporter,
)
from src.data.providers.settings import ApiProviderSettings
from tests.support.twse_current_listing_identity_fixtures import (
    FakeProvider,
    FakeWriter,
    mops_payload,
    profile_rows,
)


SNAPSHOT_DATE = date(2026, 7, 18)


def _importer(
    *,
    writer: FakeWriter,
    retrieved_at: datetime | None = None,
) -> TwseCurrentListingIdentityImporter:
    payload = mops_payload(
        profile_rows(),
        retrieved_at=(retrieved_at or datetime(2026, 7, 18, 6, tzinfo=timezone.utc)),
    )
    return TwseCurrentListingIdentityImporter(
        settings=ApiProviderSettings(),
        registry={"MOPS": FakeProvider(payload)},
        writer=writer,
    )


def test_dry_run_validates_full_snapshot_without_database_access() -> None:
    writer = FakeWriter()
    importer = _importer(writer=writer)

    summary = importer.run(snapshot_date=SNAPSHOT_DATE, dry_run=True)

    assert writer.calls == []
    assert summary.normalized_records == 500
    assert summary.database_count is None
    assert summary.system_status == "RESEARCH_ONLY"
    assert "CURRENT_MOPS_PROFILE_ONLY" in summary.reason_codes


def test_import_writes_only_source_and_unresolved_listing_evidence() -> None:
    writer = FakeWriter()
    summary = _importer(writer=writer).run(snapshot_date=SNAPSHOT_DATE)

    upserts = [call for call in writer.calls if call["operation"] == "upsert"]
    assert [call["table"] for call in upserts] == [
        "data_sources",
        "security_listing_periods",
    ]
    assert not {"securities", "security_history"} & {
        str(call["table"]) for call in writer.calls
    }
    evidence_call = upserts[1]
    assert evidence_call["on_conflict"] == (
        "source_id,source_dataset,source_event_id,source_revision_hash"
    )
    assert evidence_call["preserve_existing"] is True
    rows = cast(list[dict[str, object]], evidence_call["rows"])
    assert len(rows) == 500
    assert {row["source_id"] for row in rows} == {42}
    assert all(
        row["security_id"] is None
        and row["identity_resolution_status"] == "UNRESOLVED"
        and row["system_status"] == "RESEARCH_ONLY"
        for row in rows
    )
    assert summary.database_count == 500


def test_missing_mops_source_id_blocks_evidence_write() -> None:
    writer = FakeWriter(return_source=False)

    with pytest.raises(IngestionError) as captured:
        _ = _importer(writer=writer).run(snapshot_date=SNAPSHOT_DATE)

    assert captured.value.reason_code == "DATA_SOURCE_UPSERT_INCOMPLETE"
    assert [call["table"] for call in writer.calls] == ["data_sources"]


def test_retrieval_date_mismatch_is_visible_and_blocks_write() -> None:
    mismatched = datetime(2026, 7, 17, 6, tzinfo=timezone.utc)
    writer = FakeWriter()
    importer = _importer(writer=writer, retrieved_at=mismatched)

    summary = importer.run(snapshot_date=SNAPSHOT_DATE, dry_run=True)
    assert "SNAPSHOT_DATE_DOES_NOT_MATCH_RETRIEVAL_DATE" in summary.reason_codes

    with pytest.raises(IngestionError) as captured:
        _ = importer.run(snapshot_date=SNAPSHOT_DATE)
    assert captured.value.reason_code == (
        "CURRENT_LISTING_IDENTITY_SNAPSHOT_DATE_INVALID"
    )
    assert writer.calls == []


def test_coverage_floor_rejects_partial_profile_snapshot() -> None:
    writer = FakeWriter()
    importer = TwseCurrentListingIdentityImporter(
        settings=ApiProviderSettings(),
        registry={"MOPS": FakeProvider(mops_payload(profile_rows(499)))},
        writer=writer,
    )

    with pytest.raises(IngestionError) as captured:
        _ = importer.run(snapshot_date=SNAPSHOT_DATE, dry_run=True)
    assert captured.value.reason_code == "CURRENT_LISTING_IDENTITY_COVERAGE_TOO_LOW"
    assert writer.calls == []
