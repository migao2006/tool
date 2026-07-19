from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.config.loader import load_mvp_config
from src.pipeline.contracts import (
    PipelineBatch,
    PipelineContext,
    PipelineMode,
    PipelineStatus,
)
from src.pipeline.research_dataset import TWSE_PRICE_RESEARCH_FEATURES
from src.features.twse_price_volume_schema import (
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
)
from src.pipeline.research_fold_metrics import (
    direction_metric_summary,
    quantile_metric_summary,
    ranking_metric_summary,
)
from src.pipeline.twse_research_runner import TwsePriceResearchRunner


UTC = timezone.utc


def _frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for offset, symbol in enumerate(("2330", "2317")):
        decision_at = datetime(2026, 7, 16 + offset, 6, 30, tzinfo=UTC)
        row: dict[str, object] = {
            "symbol": symbol,
            "market": "TWSE",
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
            "reason_codes": ("UNADJUSTED_PRICE_RESEARCH_ONLY",),
            "feature_schema_hash": TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
            "label_version": "label-v1",
            "benchmark_id": "TAIEX",
            "benchmark_version": "benchmark-v1",
            "cost_profile_version": "cost-v1",
            "dataset_snapshot_id": "snapshot-v1",
            "source_hash": "a" * 64,
        }
        row.update(
            {name: 0.01 + offset * 0.001 for name in TWSE_PRICE_RESEARCH_FEATURES}
        )
        rows.append(row)
    return pd.DataFrame(rows)


def test_runner_fails_closed_when_history_cannot_preserve_holdout(
    tmp_path: Path,
) -> None:
    batch = PipelineBatch(
        records=_frame(),
        source_uri="memory://twse-research",
        source_hash="a" * 64,
    )
    context = PipelineContext(
        mode=PipelineMode.TRAIN,
        horizon=5,
        config=load_mvp_config("config/five_day_mvp.toml"),
        artifact_root=tmp_path,
    )

    result = TwsePriceResearchRunner().train(batch, context)

    assert result.status is PipelineStatus.RESEARCH_ONLY
    assert result.reason_codes == ("INSUFFICIENT_LOCKED_HOLDOUT_HISTORY",)
    assert result.records_read == 2
    assert result.source_hash == "a" * 64


def test_research_metric_helpers_report_required_metrics() -> None:
    ranking = ranking_metric_summary(
        decision_dates=[date(2026, 7, 17), date(2026, 7, 17)],
        realized_alpha=[0.02, -0.01],
        relevance=[9, 0],
        predicted_scores=[0.8, 0.2],
        eval_at=(10, 20, 50),
    )
    direction = direction_metric_summary(
        actual=["UP", "NEUTRAL", "DOWN"],
        probabilities=[(0.8, 0.1, 0.1), (0.1, 0.8, 0.1), (0.1, 0.1, 0.8)],
        p_up_threshold=0.55,
    )
    quantiles = quantile_metric_summary(
        actual=[-0.01, 0.01],
        q10=[-0.02, -0.01],
        q50=[0.0, 0.01],
        q90=[0.02, 0.03],
        raw_crossing_rate=0.25,
    )

    assert ranking["ndcg_at_10"] == 1.0
    assert ranking["rank_ic_mean"] == pytest.approx(1.0)
    assert direction["macro_f1"] == 1.0
    assert float(direction["ece"]) < 0.21
    assert quantiles["raw_crossing_rate"] == 0.25
    assert quantiles["final_crossing_rate"] == 0.0
