from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from scripts import build_tpex_research_feature_dataset as cli
from src.data.research.tpex_feature_artifact_contracts import (
    TpexFeatureArtifactReadError,
)
from src.data.research.tpex_archive_feature_contracts import (
    TPEX_ARCHIVE_SCOPE_FILTERS,
)


class _SnapshotRepository:
    def __init__(self, _: object) -> None:
        pass

    def fetch(self, **_: object) -> SimpleNamespace:
        return SimpleNamespace(snapshot_sha256="a" * 64)


class _IdentityRepository:
    def __init__(self, _: object) -> None:
        pass

    def fetch(self) -> SimpleNamespace:
        return SimpleNamespace(snapshot_sha256="b" * 64)


class _CandidateWriter:
    def __init__(self, output_path: Path, **_: object) -> None:
        self.output_path: Path = output_path


class _Audit:
    def as_json(self) -> dict[str, object]:
        return {}


class _Builder:
    def __init__(self, _: object) -> None:
        pass

    def build(self, *, writer: _CandidateWriter, **_: object) -> object:
        written_bytes = writer.output_path.write_bytes(b"new candidate")
        assert written_bytes > 0
        return _Audit()


class _RejectingReader:
    def manifest_from_parquet(self, _: Path) -> object:
        raise TpexFeatureArtifactReadError(
            "TEST_READ_BACK_REJECTED",
            "test-only read-back rejection",
        )


class _R2Factory:
    @staticmethod
    def from_env() -> object:
        return object()


def _supabase_writer(**_: object) -> object:
    return object()


def _historical_reader(_: object) -> object:
    return object()


def test_failed_read_back_preserves_previous_published_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "tpex-features.parquet"
    audit = tmp_path / "audit.json"
    _ = output.write_bytes(b"previous verified artifact")

    monkeypatch.setattr(cli, "SupabaseWriter", _supabase_writer)
    monkeypatch.setattr(cli, "HistoricalArchiveManifestRepository", _SnapshotRepository)
    monkeypatch.setattr(cli, "TpexCurrentIdentityRepository", _IdentityRepository)
    monkeypatch.setattr(cli, "R2Client", _R2Factory)
    monkeypatch.setattr(cli, "HistoricalParquetReader", _historical_reader)
    monkeypatch.setattr(cli, "TpexArchiveFeatureParquetWriter", _CandidateWriter)
    monkeypatch.setattr(cli, "TpexArchiveFeatureDatasetBuilder", _Builder)
    monkeypatch.setattr(cli, "TpexFeatureArtifactReader", _RejectingReader)

    exit_code = cli.main(["--output", str(output), "--audit", str(audit)])

    assert exit_code == 1
    assert output.read_bytes() == b"previous verified artifact"
    assert not list(tmp_path.glob("*.candidate"))
    audit_payload = cast(
        dict[str, object], json.loads(audit.read_text(encoding="utf-8"))
    )
    assert audit_payload["reason_codes"] == ["TEST_READ_BACK_REJECTED"]
    assert audit_payload["usage_scope"] == "FEATURE_RESEARCH_ONLY"


def test_cli_uses_only_tpex_archive_scope() -> None:
    assert TPEX_ARCHIVE_SCOPE_FILTERS["scheduled_market"] == "eq.TPEX"
    assert TPEX_ARCHIVE_SCOPE_FILTERS["asset_type"] == "eq.COMMON_STOCK"
