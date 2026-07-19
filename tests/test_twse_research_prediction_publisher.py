from __future__ import annotations

# pyright: reportAny=false, reportMissingTypeStubs=false

from dataclasses import replace
from datetime import date, datetime, timezone
import json
from pathlib import Path

import pandas as pd
import pytest

from src.pipeline.twse_research_evaluation_contracts import (
    DirectionEvaluation,
    QuantileEvaluation,
    RankEvaluation,
)
from src.pipeline.twse_research_prediction_contracts import (
    RESEARCH_PREDICTION_CONTRACT_VERSION,
)
from src.pipeline.twse_research_prediction_publisher import (
    TwseResearchPredictionPublisher,
    build_fold_research_predictions,
)


UTC = timezone.utc


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "1101",
                "market": "TWSE",
                "decision_date": date(2025, 12, 31),
                "decision_at": datetime(2025, 12, 31, 6, 30, tzinfo=UTC),
                "available_at": datetime(2025, 12, 31, 6, 0, tzinfo=UTC),
                "horizon": 5,
                "round_trip_cost_rate": 0.005,
                "data_quality_status": "WARN",
                "reason_codes": ("TWSE_PRICE_ONLY_RESEARCH",),
            },
            {
                "symbol": "2330",
                "market": "TWSE",
                "decision_date": date(2026, 1, 2),
                "decision_at": datetime(2026, 1, 2, 6, 30, tzinfo=UTC),
                "available_at": datetime(2026, 1, 2, 6, 0, tzinfo=UTC),
                "horizon": 5,
                "round_trip_cost_rate": 0.006,
                "data_quality_status": "WARN",
                "reason_codes": ("TWSE_PRICE_ONLY_RESEARCH",),
            },
            {
                "symbol": "2317",
                "market": "TWSE",
                "decision_date": date(2026, 1, 2),
                "decision_at": datetime(2026, 1, 2, 6, 30, tzinfo=UTC),
                "available_at": datetime(2026, 1, 2, 6, 0, tzinfo=UTC),
                "horizon": 5,
                "round_trip_cost_rate": 0.004,
                "data_quality_status": "PASS",
                "reason_codes": ("TWSE_PRICE_ONLY_RESEARCH",),
            },
        ]
    )


def _fold_batch():
    return build_fold_research_predictions(
        frame=_frame(),
        train_indices=(0,),
        test_indices=(1, 2),
        fold_number=1,
        rank=RankEvaluation(metrics={}, model_scores=(0.2, 0.8)),
        direction=DirectionEvaluation(
            metrics={},
            probabilities=((0.6, 0.3, 0.1), (0.2, 0.5, 0.3)),
            calibration_version="probability-calibration-v1",
        ),
        quantiles=QuantileEvaluation(
            metrics={},
            gross_quantiles=((-0.02, 0.01, 0.05), (-0.03, 0.0, 0.04)),
            net_quantiles=((-0.026, 0.004, 0.044), (-0.034, -0.004, 0.036)),
            raw_crossed=(False, True),
            calibration_version="interval-calibration-v1",
        ),
    )


def test_fold_predictions_keep_rank_as_the_only_ordering_source() -> None:
    batch = _fold_batch()

    assert [value.symbol for value in batch.predictions] == ["2317", "2330"]
    assert [value.global_rank for value in batch.predictions] == [1, 2]
    assert [value.rank_score for value in batch.predictions] == [100.0, 0.0]
    assert batch.predictions[1].calibrated_p_up == 0.6
    assert batch.predictions[1].net_q50 == 0.004
    assert batch.training_end_date == date(2025, 12, 31)


def test_publisher_writes_versioned_read_back_verified_oos_snapshot(
    tmp_path: Path,
) -> None:
    target = tmp_path / "snapshot.json"
    published = TwseResearchPredictionPublisher().publish(
        target,
        fold_batches=(_fold_batch(),),
        horizon=5,
        model_version="twse-price-research-h5-v1",
        feature_schema_hash="f" * 64,
        input_artifact_sha256="b" * 64,
        provenance={
            "dataset_snapshot_id": "d" * 64,
            "source_hash": "a" * 64,
            "label_version": "label-v1",
            "benchmark_id": "TAIEX",
            "benchmark_version": "official-price-index-v1",
            "cost_profile_version": "tw-stock-v1:base_cost",
        },
        model_metadata={"rank_model": "LightGBM", "random_seed": 42},
        cost_metadata={"profile": "base_cost"},
        validation={
            "fold_count": 1,
            "locked_holdout_executed": False,
        },
        reason_codes=(
            "TWSE_PRICE_ONLY_RESEARCH",
            "LOCKED_HOLDOUT_NOT_EXECUTED",
        ),
    )

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["artifact_contract_version"] == (
        RESEARCH_PREDICTION_CONTRACT_VERSION
    )
    assert payload["system_status"] == "RESEARCH_ONLY"
    assert payload["horizon"] == 5
    assert payload["as_of_date"] == "2026-01-02"
    assert payload["training_end_date"] == "2025-12-31"
    assert payload["snapshot_sha256"] == published.snapshot.snapshot_sha256
    assert len(published.artifact_sha256) == 64
    assert [row["symbol"] for row in payload["predictions"]] == ["2317", "2330"]
    assert "decision" not in payload["predictions"][0]
    assert "name" not in payload["predictions"][0]
    assert "industry" not in payload["predictions"][0]


def test_contract_rejects_unreleased_horizon() -> None:
    values = _fold_batch().predictions[0]

    with pytest.raises(NotImplementedError):
        _ = replace(values, horizon=3)


def test_publisher_rejects_missing_provenance(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="benchmark_version"):
        _ = TwseResearchPredictionPublisher().publish(
            tmp_path / "snapshot.json",
            fold_batches=(_fold_batch(),),
            horizon=5,
            model_version="twse-price-research-h5-v1",
            feature_schema_hash="f" * 64,
            input_artifact_sha256="b" * 64,
            provenance={
                "dataset_snapshot_id": "d" * 64,
                "source_hash": "a" * 64,
                "label_version": "label-v1",
                "benchmark_id": "TAIEX",
                "cost_profile_version": "tw-stock-v1:base_cost",
            },
            model_metadata={"rank_model": "LightGBM"},
            cost_metadata={"profile": "base_cost"},
            validation={"fold_count": 1},
            reason_codes=("TWSE_PRICE_ONLY_RESEARCH",),
        )
