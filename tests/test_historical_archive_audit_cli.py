from __future__ import annotations

import json

import pytest

from scripts import audit_historical_r2_archive
from src.data.archive.manifest_repository import HistoricalArchiveManifestSnapshot
from src.quality.historical_archive_audit import HistoricalArchiveAuditResult


def test_cli_writes_research_only_full_audit_report(tmp_path, monkeypatch) -> None:
    class FakeRepository:
        def __init__(self, source) -> None:
            del source

        def fetch(self, *, max_objects=None):
            assert max_objects is None
            return HistoricalArchiveManifestSnapshot(
                rows=(
                    {
                        "archive_id": 7,
                        "object_key": "history/2330.parquet",
                        "row_count": 10,
                        "byte_size": 100,
                    },
                ),
                snapshot_sha256="a" * 64,
                complete=True,
                high_water_archive_id=7,
            )

    monkeypatch.setattr(
        audit_historical_r2_archive, "SupabaseWriter", lambda **kwargs: object()
    )
    monkeypatch.setattr(
        audit_historical_r2_archive,
        "HistoricalArchiveManifestRepository",
        FakeRepository,
    )
    monkeypatch.setattr(
        audit_historical_r2_archive.R2Client, "from_env", lambda: object()
    )
    monkeypatch.setattr(
        audit_historical_r2_archive,
        "HistoricalParquetReader",
        lambda client: object(),
    )

    def successful_audit(rows, *, reader, **kwargs):
        del rows, reader
        kwargs["progress_callback"](1, 7, 10, 100, ())
        return HistoricalArchiveAuditResult(
            passed=True,
            status="PASS",
            object_count=1,
            row_count=10,
            byte_count=100,
            reason_codes=(),
        )

    monkeypatch.setattr(
        audit_historical_r2_archive,
        "audit_historical_archive",
        successful_audit,
    )
    output = tmp_path / "audit.json"

    exit_code = audit_historical_r2_archive.main(["--output", str(output)])
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert payload["integrity_status"] == "PASS"
    assert payload["system_status"] == "RESEARCH_ONLY"
    assert payload["audit_scope"] == "FULL"
    assert payload["point_in_time_status"] == "UNVERIFIED"
    assert payload["audit_workers"] == 8
    assert payload["audit_batch_size"] == 64
    assert payload["inspected_object_count"] == 1
    assert payload["last_inspected_archive_id"] == 7
    assert payload["snapshot_high_water_archive_id"] == 7


def test_cli_atomically_retains_exact_progress_if_audit_is_interrupted(
    tmp_path, monkeypatch
) -> None:
    class FakeRepository:
        def __init__(self, source) -> None:
            del source

        def fetch(self, *, max_objects=None):
            assert max_objects is None
            return HistoricalArchiveManifestSnapshot(
                rows=(
                    {
                        "archive_id": 17,
                        "object_key": "history/2330.parquet",
                        "row_count": 10,
                        "byte_size": 100,
                    },
                ),
                snapshot_sha256="a" * 64,
                complete=True,
                high_water_archive_id=17,
            )

    def interrupted_audit(rows, *, reader, **kwargs):
        del rows, reader
        callback = kwargs["progress_callback"]
        callback(1, 17, 10, 100, ())
        raise KeyboardInterrupt

    monkeypatch.setattr(
        audit_historical_r2_archive, "SupabaseWriter", lambda **kwargs: object()
    )
    monkeypatch.setattr(
        audit_historical_r2_archive,
        "HistoricalArchiveManifestRepository",
        FakeRepository,
    )
    monkeypatch.setattr(
        audit_historical_r2_archive.R2Client, "from_env", lambda: object()
    )
    monkeypatch.setattr(
        audit_historical_r2_archive,
        "HistoricalParquetReader",
        lambda client: object(),
    )
    monkeypatch.setattr(
        audit_historical_r2_archive,
        "audit_historical_archive",
        interrupted_audit,
    )
    output = tmp_path / "audit.json"

    with pytest.raises(KeyboardInterrupt):
        _ = audit_historical_r2_archive.main(["--output", str(output)])
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["integrity_status"] == "IN_PROGRESS"
    assert payload["audit_scope"] == "FULL_IN_PROGRESS"
    assert payload["manifest_snapshot_sha256"] == "a" * 64
    assert payload["object_count"] == 1
    assert payload["inspected_object_count"] == 1
    assert payload["last_inspected_archive_id"] == 17
    assert payload["snapshot_high_water_archive_id"] == 17
    assert payload["row_count"] == 10
    assert payload["byte_count"] == 100
    assert payload["planned_row_count"] == 10
    assert payload["planned_byte_count"] == 100
