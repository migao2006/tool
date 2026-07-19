from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import build_twse_research_feature_dataset as cli
from src.data.research.twse_feature_artifact_contracts import (
    TwseFeatureArtifactReadError,
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
        self.output_path = output_path


class _Builder:
    def __init__(self, _: object) -> None:
        pass

    def build(self, *, writer: _CandidateWriter, **_: object) -> object:
        writer.output_path.write_bytes(b"new candidate")
        return SimpleNamespace(as_json=lambda: {})


class _RejectingReader:
    def manifest_from_parquet(self, _: Path) -> object:
        raise TwseFeatureArtifactReadError(
            "TEST_READ_BACK_REJECTED",
            "test-only read-back rejection",
        )


def test_failed_read_back_preserves_previous_published_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "twse-features.parquet"
    audit = tmp_path / "audit.json"
    output.write_bytes(b"previous verified artifact")

    monkeypatch.setattr(cli, "SupabaseWriter", lambda **_: object())
    monkeypatch.setattr(cli, "HistoricalArchiveManifestRepository", _SnapshotRepository)
    monkeypatch.setattr(cli, "TwseCurrentIdentityRepository", _IdentityRepository)
    monkeypatch.setattr(cli, "R2Client", SimpleNamespace(from_env=lambda: object()))
    monkeypatch.setattr(cli, "HistoricalParquetReader", lambda _: object())
    monkeypatch.setattr(cli, "TwseArchiveFeatureParquetWriter", _CandidateWriter)
    monkeypatch.setattr(cli, "TwseArchiveFeatureDatasetBuilder", _Builder)
    monkeypatch.setattr(cli, "TwseFeatureArtifactReader", _RejectingReader)

    exit_code = cli.main(["--output", str(output), "--audit", str(audit)])

    assert exit_code == 1
    assert output.read_bytes() == b"previous verified artifact"
    assert not list(tmp_path.glob("*.candidate"))
