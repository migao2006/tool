from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from src.config.loader import load_mvp_config
from src.core.research_prediction_contract import (
    TPEX_RESEARCH_PREDICTION_CONTRACT_VERSION,
)
from src.features.tpex_price_volume_schema import (
    TPEX_PRICE_VOLUME_FEATURE_NAMES,
    TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
)
from src.pipeline.contracts import (
    PipelineBatch,
    PipelineContext,
    PipelineMode,
    PipelineStatus,
)
from src.pipeline.tpex_research_runner import TpexPriceResearchRunner
from src.pipeline.twse_research_evaluation_contracts import (
    DirectionEvaluation,
    QuantileEvaluation,
    RankEvaluation,
)
from src.pipeline.twse_research_prediction_publisher import (
    TwseResearchPredictionPublisher,
    build_fold_research_predictions,
)


UTC = timezone.utc


def _frame(*, market: str = "TPEX") -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for offset, symbol in enumerate(("6488", "5274")):
        decision_at = datetime(2026, 7, 16 + offset, 6, 30, tzinfo=UTC)
        row: dict[str, object] = {
            "symbol": symbol,
            "market": market,
            "horizon": 5,
            "decision_date": decision_at.date(),
            "decision_at": decision_at,
            "available_at": decision_at,
            "source_latest_available_at": decision_at,
            "availability_basis": "SOURCE_AVAILABLE_AT",
            "entry_at": decision_at + timedelta(days=1),
            "exit_at": decision_at + timedelta(days=7),
            "gross_return": 0.03 - offset * 0.02,
            "net_return": 0.024 - offset * 0.02,
            "net_alpha": 0.012 - offset * 0.01,
            "round_trip_cost_rate": 0.006,
            "direction": "UP" if offset == 0 else "NEUTRAL",
            "data_quality_status": "WARN",
            "system_status": "RESEARCH_ONLY",
            "usage_scope": "MODEL_RESEARCH_ONLY",
            "reason_codes": ("TPEX_PRICE_ONLY_RESEARCH",),
            "feature_schema_hash": TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
            "label_version": "tpex-research-unadjusted-open-close-5d-v1",
            "benchmark_id": "TPEX_PRICE_INDEX",
            "benchmark_version": "tpex-price-index-v1",
            "cost_profile_version": "tw_stock_swing_v1:base_cost",
            "dataset_snapshot_id": "d" * 64,
            "source_hash": "a" * 64,
        }
        row.update(
            {name: 0.01 + offset * 0.001 for name in TPEX_PRICE_VOLUME_FEATURE_NAMES}
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _context(tmp_path: Path) -> PipelineContext:
    return PipelineContext(
        mode=PipelineMode.TRAIN,
        horizon=5,
        config=load_mvp_config("config/five_day_mvp.toml"),
        artifact_root=tmp_path,
    )


def test_tpex_runner_accepts_venue_schema_before_history_gate(tmp_path: Path) -> None:
    result = TpexPriceResearchRunner().train(
        PipelineBatch(
            records=_frame(),
            source_uri="memory://tpex-research",
            source_hash="a" * 64,
        ),
        _context(tmp_path),
    )

    assert result.status is PipelineStatus.RESEARCH_ONLY
    assert result.reason_codes == ("INSUFFICIENT_LOCKED_HOLDOUT_HISTORY",)
    assert result.model_version == "tpex-price-research-h5-v1"
    assert result.feature_schema_hash == TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH


def test_tpex_runner_rejects_twse_rows(tmp_path: Path) -> None:
    result = TpexPriceResearchRunner().train(
        PipelineBatch(
            records=_frame(market="TWSE"),
            source_uri="memory://wrong-market",
            source_hash="a" * 64,
        ),
        _context(tmp_path),
    )

    assert result.reason_codes == ("TPEX_RESEARCH_DATASET_INVALID",)


def test_fold_prediction_preserves_tpex_market() -> None:
    frame = _frame()
    batch = build_fold_research_predictions(
        frame=frame,
        train_indices=(0,),
        test_indices=(1,),
        fold_number=1,
        rank=RankEvaluation(metrics={}, model_scores=(0.8,)),
        direction=DirectionEvaluation(
            metrics={},
            probabilities=((0.6, 0.3, 0.1),),
            calibration_version="probability-calibration-v1",
        ),
        quantiles=QuantileEvaluation(
            metrics={},
            gross_quantiles=((-0.02, 0.01, 0.05),),
            net_quantiles=((-0.026, 0.004, 0.044),),
            raw_crossed=(False,),
            calibration_version="interval-calibration-v1",
        ),
    )

    assert batch.training_end_date == date(2026, 7, 16)
    assert batch.predictions[0].market == "TPEX"
    assert batch.predictions[0].symbol == "5274"


def test_tpex_prediction_uses_independent_snapshot_contract(tmp_path: Path) -> None:
    frame = _frame()
    batch = build_fold_research_predictions(
        frame=frame,
        train_indices=(0,),
        test_indices=(1,),
        fold_number=1,
        rank=RankEvaluation(metrics={}, model_scores=(0.8,)),
        direction=DirectionEvaluation(
            metrics={},
            probabilities=((0.6, 0.3, 0.1),),
            calibration_version="probability-calibration-v1",
        ),
        quantiles=QuantileEvaluation(
            metrics={},
            gross_quantiles=((-0.02, 0.01, 0.05),),
            net_quantiles=((-0.026, 0.004, 0.044),),
            raw_crossed=(False,),
            calibration_version="interval-calibration-v1",
        ),
    )
    published = TwseResearchPredictionPublisher().publish(
        tmp_path / "tpex.json",
        fold_batches=(batch,),
        horizon=5,
        model_version="tpex-price-research-h5-v1",
        feature_schema_hash=TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
        input_artifact_sha256="a" * 64,
        provenance={
            "dataset_snapshot_id": "d" * 64,
            "source_hash": "b" * 64,
            "label_version": "tpex-research-unadjusted-open-close-5d-v1",
            "benchmark_id": "TPEX_PRICE_INDEX",
            "benchmark_version": "tpex-price-index-v1",
            "cost_profile_version": "tw_stock_swing_v1:base_cost",
        },
        model_metadata={"rank_model": "LightGBM"},
        cost_metadata={"cost_profile": "base_cost"},
        validation={"fold_count": 1, "locked_holdout_executed": False},
        reason_codes=("TPEX_PRICE_ONLY_RESEARCH",),
    )

    payload = published.snapshot.to_dict()
    assert payload["market"] == "TPEX"
    assert payload["artifact_contract_version"] == (
        TPEX_RESEARCH_PREDICTION_CONTRACT_VERSION
    )
