from __future__ import annotations

import pytest

from scripts.publish_tpex_daily_research_snapshot import (
    TpexDailyResearchPublishError,
    _inference_feature_source,
)


def test_local_publish_does_not_forge_workflow_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    assert _inference_feature_source() is None


def test_github_publish_requires_complete_daily_delta_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("TPEX_INFERENCE_FEATURE_SOURCE_RUN_ID", raising=False)

    with pytest.raises(TpexDailyResearchPublishError) as captured:
        _ = _inference_feature_source()

    assert captured.value.reason_code == (
        "TPEX_INFERENCE_FEATURE_SOURCE_PROVENANCE_INVALID"
    )


def test_github_publish_persists_non_secret_daily_delta_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("TPEX_INFERENCE_FEATURE_SOURCE_RUN_ID", "29740000000")
    monkeypatch.setenv("TPEX_INFERENCE_FEATURE_SOURCE_RUN_SHA", "f" * 40)
    monkeypatch.setenv("TPEX_INFERENCE_FEATURE_SOURCE_ARTIFACT_ID", "8459000000")
    monkeypatch.setenv(
        "TPEX_INFERENCE_FEATURE_SOURCE_ARTIFACT_DIGEST",
        "sha256:" + "e" * 64,
    )

    provenance = _inference_feature_source()

    assert provenance is not None
    assert provenance["artifact_kind"] == "TPEX_DAILY_FEATURE_DELTA"
    assert provenance["run_id"] == "29740000000"
    assert provenance["artifact_digest"] == "sha256:" + "e" * 64
