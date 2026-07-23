from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import pytest

import scripts.publish_stored_research_snapshot as stored_publish
from scripts.publish_stored_research_snapshot import _load_snapshot
from src.data.ingestion.contracts import IngestionError
from src.data.research.twse_research_prediction_supabase_contracts import (
    ResearchSupabasePublishResult,
)


AS_OF_DATE = date(2026, 7, 20)


def _payload(*, market: str = "TWSE") -> dict[str, object]:
    content: dict[str, object] = {
        "artifact_contract_version": (
            "twse-research-prediction.v1" if market == "TWSE" else "tpex-research-prediction.v1"
        ),
        "system_status": "RESEARCH_ONLY",
        "as_of_date": AS_OF_DATE.isoformat(),
        "decision_at": "2026-07-20T13:30:00+08:00",
        "horizon": 5,
        "predictions": [
            {
                "symbol": f"{index:04d}",
                "market": market,
                "decision_date": AS_OF_DATE.isoformat(),
                "horizon": 5,
            }
            for index in range(1_000, 1_500)
        ],
        "model_version": "research-model.v1",
        "feature_schema_hash": "1" * 64,
        "dataset_snapshot_id": "2" * 64,
        "source_hash": "3" * 64,
        "input_artifact_sha256": "4" * 64,
        "label_version": "research-label.v1",
        "benchmark_id": "TAIEX_PRICE_INDEX",
        "benchmark_version": "price-index.v1",
        "cost_profile_version": "base-cost.v1",
        "training_end_date": "2026-07-17",
        "model_metadata": {"scope": "test"},
        "cost_metadata": {"scope": "test"},
        "validation": {"status": "RESEARCH_ONLY"},
        "reason_codes": ["LOCKED_HOLDOUT_NOT_EXECUTED"],
    }
    if market != "TWSE":
        content["market"] = market
    digest = sha256(
        json.dumps(
            content,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {**content, "snapshot_sha256": digest}


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_load_snapshot_accepts_one_exact_immutable_release(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    _write(snapshot, _payload(market="TPEX"))

    loaded = _load_snapshot(snapshot, market="TPEX", as_of_date=AS_OF_DATE)

    assert loaded["market"] == "TPEX"
    assert loaded["as_of_date"] == AS_OF_DATE.isoformat()
    assert len(loaded["predictions"]) == 500  # type: ignore[arg-type]


def test_load_snapshot_rejects_tampering_and_wrong_release_date(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    payload = _payload()
    predictions = payload["predictions"]
    assert isinstance(predictions, list)
    first = predictions[0]
    assert isinstance(first, dict)
    first["symbol"] = "9999"
    _write(snapshot, payload)

    with pytest.raises(ValueError, match="RESEARCH_SNAPSHOT_HASH_MISMATCH"):
        _load_snapshot(snapshot, market="TWSE", as_of_date=AS_OF_DATE)

    _write(snapshot, _payload())
    with pytest.raises(ValueError, match="RESEARCH_SNAPSHOT_REQUIRED_DATE_MISMATCH"):
        _load_snapshot(snapshot, market="TWSE", as_of_date=date(2026, 7, 21))


def test_stored_publisher_allows_one_transient_data_api_stall_to_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeWriter:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(stored_publish, "SupabaseWriter", FakeWriter)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-secret")

    _ = stored_publish._research_writer()

    assert captured["timeout"] == 60.0


def test_stored_publisher_replays_an_immutable_publish_after_connection_errors() -> None:
    attempts = 0
    delays: list[float] = []
    expected = ResearchSupabasePublishResult(
        prediction_run_id=11,
        prediction_count=1_068,
        target_environment="production",
        decision_gate_count=8_544,
    )

    def publish_once() -> ResearchSupabasePublishResult:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise IngestionError(
                "SUPABASE_CONNECTION_ERROR",
                "Supabase write request could not be completed",
            )
        return expected

    result = stored_publish._publish_with_connection_retry(
        publish_once,
        sleeper=delays.append,
    )

    assert result == expected
    assert attempts == 3
    assert delays == [1.0, 2.0]


def test_stored_publisher_does_not_replay_a_rejected_publish() -> None:
    attempts = 0
    delays: list[float] = []

    def publish_once() -> ResearchSupabasePublishResult:
        nonlocal attempts
        attempts += 1
        raise IngestionError(
            "SUPABASE_WRITE_REJECTED",
            "Supabase rejected the immutable publish",
        )

    with pytest.raises(IngestionError) as captured:
        stored_publish._publish_with_connection_retry(
            publish_once,
            sleeper=delays.append,
        )

    assert captured.value.reason_code == "SUPABASE_WRITE_REJECTED"
    assert attempts == 1
    assert delays == []


def test_stored_publisher_exhausts_connection_retries() -> None:
    attempts = 0
    delays: list[float] = []

    def publish_once() -> ResearchSupabasePublishResult:
        nonlocal attempts
        attempts += 1
        raise IngestionError(
            "SUPABASE_CONNECTION_ERROR",
            "Supabase write request could not be completed",
        )

    with pytest.raises(IngestionError) as captured:
        stored_publish._publish_with_connection_retry(
            publish_once,
            sleeper=delays.append,
        )

    assert captured.value.reason_code == "SUPABASE_CONNECTION_ERROR"
    assert attempts == 3
    assert delays == [1.0, 2.0]
