from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from pytest import MonkeyPatch

from scripts import audit_historical_dataset_readiness
from src.data.archive.manifest_repository import HistoricalArchiveManifestSnapshot
from src.quality.historical_dataset_readiness import HistoricalDatasetReadinessMetrics


def test_cli_reports_blocked_research_state_without_fake_readiness(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    archive_path = tmp_path / "archive.json"
    _ = archive_path.write_text(
        json.dumps(
            {
                "integrity_status": "PASS",
                "audit_scope": "FULL",
                "manifest_snapshot_sha256": "a" * 64,
                "snapshot_high_water_archive_id": 1,
                "object_count": 1,
                "row_count": 10,
            }
        ),
        encoding="utf-8",
    )

    def fake_writer(**kwargs: object) -> object:
        del kwargs
        return object()

    monkeypatch.setattr(
        audit_historical_dataset_readiness, "SupabaseWriter", fake_writer
    )

    class FakeManifestRepository:
        def __init__(self, source: object) -> None:
            del source

        def fetch(self, *, through_archive_id=None):
            assert through_archive_id == 1
            return HistoricalArchiveManifestSnapshot(
                rows=({"source_symbol": "2330", "scheduled_market": "TWSE"},),
                snapshot_sha256="a" * 64,
                complete=True,
                high_water_archive_id=1,
            )

    class FakeReadinessRepository:
        def __init__(self, source: object) -> None:
            del source

        def collect(self, **kwargs: object) -> HistoricalDatasetReadinessMetrics:
            del kwargs
            return HistoricalDatasetReadinessMetrics(
                archive_integrity_status="PASS",
                archive_object_count=1,
                archive_row_count=10,
                twse_archive_symbol_count=1,
                tpex_archive_symbol_count=0,
                twse_pit_covered_archive_symbol_count=0,
                tpex_pit_covered_archive_symbol_count=0,
                pit_covered_trading_session_count=0,
                twse_verified_listing_period_count=0,
                tpex_verified_listing_period_count=0,
                conflicting_listing_period_count=0,
                twse_verified_calendar_session_count=0,
                tpex_verified_calendar_session_count=0,
                verified_security_state_count=0,
                verified_company_action_coverage_count=0,
                unresolved_delisting_count=843,
                canonical_contract_object_count=0,
                canonical_production_row_count=0,
            )

    monkeypatch.setattr(
        audit_historical_dataset_readiness,
        "HistoricalArchiveManifestRepository",
        FakeManifestRepository,
    )
    monkeypatch.setattr(
        audit_historical_dataset_readiness,
        "HistoricalReadinessRepository",
        FakeReadinessRepository,
    )
    output = tmp_path / "readiness.json"

    exit_code = audit_historical_dataset_readiness.main(
        [
            "--archive-audit",
            str(archive_path),
            "--output",
            str(output),
        ]
    )
    raw_payload = cast(object, json.loads(output.read_text(encoding="utf-8")))
    assert isinstance(raw_payload, Mapping)
    payload = cast(Mapping[str, object], raw_payload)

    assert exit_code == 0
    assert payload["canonicalization_status"] == "BLOCKED"
    assert payload["canonicalization_ready"] is False
    assert payload["readiness_status"] == "BLOCKED"
    assert payload["dataset_build_ready"] is False
    assert payload["system_status"] == "RESEARCH_ONLY"
    reason_codes = payload["reason_codes"]
    assert isinstance(reason_codes, list)
    assert "CANONICAL_PRODUCTION_ROWS_EMPTY" in reason_codes


def test_cli_fails_if_manifest_snapshot_changes_after_integrity_audit(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    archive_path = tmp_path / "archive.json"
    _ = archive_path.write_text(
        json.dumps(
            {
                "integrity_status": "PASS",
                "audit_scope": "FULL",
                "manifest_snapshot_sha256": "a" * 64,
                "snapshot_high_water_archive_id": 1,
                "object_count": 1,
                "row_count": 10,
            }
        ),
        encoding="utf-8",
    )

    def fake_writer(**_kwargs: object) -> object:
        return object()

    monkeypatch.setattr(
        audit_historical_dataset_readiness,
        "SupabaseWriter",
        fake_writer,
    )

    class ChangedManifestRepository:
        def __init__(self, source: object) -> None:
            del source

        def fetch(
            self, *, through_archive_id=None
        ) -> HistoricalArchiveManifestSnapshot:
            assert through_archive_id == 1
            return HistoricalArchiveManifestSnapshot(
                rows=({"source_symbol": "2330", "scheduled_market": "TWSE"},),
                snapshot_sha256="b" * 64,
                complete=True,
                high_water_archive_id=1,
            )

    monkeypatch.setattr(
        audit_historical_dataset_readiness,
        "HistoricalArchiveManifestRepository",
        ChangedManifestRepository,
    )
    output = tmp_path / "readiness.json"

    exit_code = audit_historical_dataset_readiness.main(
        ["--archive-audit", str(archive_path), "--output", str(output)]
    )
    payload = cast(
        Mapping[str, object],
        json.loads(output.read_text(encoding="utf-8")),
    )

    assert exit_code == 1
    assert payload["canonicalization_status"] == "BLOCKED"
    assert payload["canonicalization_ready"] is False
    assert payload["system_status"] == "FAIL"
    assert payload["dataset_build_ready"] is False
    assert "changed after" in str(payload["message"])
