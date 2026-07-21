from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import pytest

from scripts.publish_stored_research_snapshot import _load_snapshot


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
