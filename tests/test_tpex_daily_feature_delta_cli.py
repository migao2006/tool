from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from scripts import build_tpex_daily_feature_delta as cli
from src.data.research.tpex_daily_feature_delta_contracts import (
    TpexDailyFeatureDeltaError,
)


class _ManifestRepository:
    def __init__(self, _: object) -> None:
        pass

    def fetch(self, **_: object) -> object:
        return SimpleNamespace(snapshot_sha256="a" * 64)


class _IdentityRepository:
    def __init__(self, _: object) -> None:
        pass

    def fetch(self) -> object:
        return SimpleNamespace(snapshot_sha256="b" * 64)


class _DailyRepository:
    def __init__(self, _: object) -> None:
        pass

    def fetch_range(self, **_: object) -> object:
        return SimpleNamespace(snapshot_sha256="c" * 64)


class _CandidateWriter:
    def __init__(self, output_path: Path, **_: object) -> None:
        self.output_path = output_path


class _Audit:
    def as_json(self) -> dict[str, object]:
        return {}


class _Builder:
    def __init__(self, _: object) -> None:
        pass

    def build(self, *, writer: _CandidateWriter, **_: object) -> object:
        _ = writer.output_path.write_bytes(b"new candidate")
        return _Audit()


class _RejectingReader:
    def manifest_from_parquet(self, _: Path) -> object:
        raise TpexDailyFeatureDeltaError(
            "TEST_DAILY_DELTA_READ_BACK_REJECTED",
            "test-only read-back rejection",
        )


class _R2Factory:
    @staticmethod
    def from_env() -> object:
        return object()


def test_failed_read_back_preserves_previous_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "tpex-daily-feature-delta.parquet"
    audit = tmp_path / "audit.json"
    _ = output.write_bytes(b"previous verified delta")

    monkeypatch.setattr(cli, "SupabaseWriter", lambda **_: object())
    monkeypatch.setattr(cli, "HistoricalArchiveManifestRepository", _ManifestRepository)
    monkeypatch.setattr(cli, "TpexCurrentIdentityRepository", _IdentityRepository)
    monkeypatch.setattr(cli, "TpexDailyBarRepository", _DailyRepository)
    monkeypatch.setattr(cli, "daily_delta_start_date", lambda _: date(2026, 7, 18))
    monkeypatch.setattr(cli, "R2Client", _R2Factory)
    monkeypatch.setattr(cli, "HistoricalParquetReader", lambda _: object())
    monkeypatch.setattr(cli, "TpexDailyFeatureDeltaWriter", _CandidateWriter)
    monkeypatch.setattr(cli, "TpexDailyFeatureDeltaBuilder", _Builder)
    monkeypatch.setattr(cli, "TpexDailyFeatureDeltaReader", _RejectingReader)

    exit_code = cli.main(
        [
            "--as-of-date",
            "2026-07-20",
            "--output",
            str(output),
            "--audit",
            str(audit),
        ]
    )

    assert exit_code == 1
    assert output.read_bytes() == b"previous verified delta"
    assert not list(tmp_path.glob("*.candidate"))
    audit_payload = cast(
        dict[str, object], json.loads(audit.read_text(encoding="utf-8"))
    )
    assert audit_payload["as_of_date"] == "2026-07-20"
    assert audit_payload["reason_codes"] == ["TEST_DAILY_DELTA_READ_BACK_REJECTED"]
    assert audit_payload["usage_scope"] == "FEATURE_RESEARCH_ONLY"


def test_cli_rejects_non_iso_date() -> None:
    with pytest.raises(SystemExit):
        _ = cli.main(
            [
                "--as-of-date",
                "07/20/2026",
                "--output",
                "ignored.parquet",
                "--audit",
                "ignored.json",
            ]
        )
