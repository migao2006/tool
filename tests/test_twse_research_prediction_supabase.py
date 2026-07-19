from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
from typing import cast

import pytest

from src.core.research_prediction_contract import (
    RESEARCH_PREDICTION_CONTRACT_VERSION,
)
from src.data.research.twse_research_prediction_supabase import (
    TwseResearchPredictionSupabasePublisher,
)


class _Writer:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, list[dict[str, object]]]] = []

    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]:
        del select, filters, limit
        assert table == "securities"
        return [
            {
                "security_id": 2330,
                "symbol": "2330",
                "market": "TWSE",
                "asset_type": "COMMON_STOCK",
            }
        ]

    def upsert(
        self,
        table: str,
        rows: Sequence[Mapping[str, object]],
        *,
        on_conflict: str,
        select: str | None = None,
        return_rows: bool = False,
        preserve_existing: bool = False,
    ) -> list[dict[str, object]]:
        del on_conflict, select, preserve_existing
        materialized = [dict(value) for value in rows]
        self.upserts.append((table, materialized))
        if table == "prediction_runs" and return_rows:
            return [{"prediction_run_id": 7}]
        return []


def _payload() -> dict[str, object]:
    prediction = {
        "symbol": "2330",
        "market": "TWSE",
        "decision_date": "2026-01-02",
        "decision_at": "2026-01-02T06:30:00+00:00",
        "horizon": 5,
        "fold_number": 0,
        "evaluation_scope": "OUT_OF_SAMPLE_TEST",
        "model_raw_score": 0.8,
        "rank_score": 100.0,
        "global_rank": 1,
        "global_rank_percentile": 1.0,
        "calibrated_p_up": 0.6,
        "calibrated_p_neutral": 0.3,
        "calibrated_p_down": 0.1,
        "calibration_version": "probability-calibration-v1",
        "gross_q10": -0.02,
        "gross_q50": 0.01,
        "gross_q90": 0.05,
        "net_q10": -0.026,
        "net_q50": 0.004,
        "net_q90": 0.044,
        "interval_width": 0.07,
        "calibration_status": "CALIBRATED:interval-calibration-v1",
        "quantile_crossing_before_calibration": False,
        "estimated_round_trip_cost": 0.006,
        "latest_available_at": "2026-01-02T06:00:00+00:00",
        "data_quality_status": "WARN",
        "reason_codes": ["TWSE_PRICE_ONLY_RESEARCH"],
    }
    payload: dict[str, object] = {
        "artifact_contract_version": RESEARCH_PREDICTION_CONTRACT_VERSION,
        "system_status": "RESEARCH_ONLY",
        "as_of_date": "2026-01-02",
        "decision_at": "2026-01-02T06:30:00+00:00",
        "horizon": 5,
        "predictions": [prediction],
        "model_version": "twse-price-research-h5-v1",
        "feature_schema_hash": "f" * 64,
        "dataset_snapshot_id": "d" * 64,
        "source_hash": "a" * 64,
        "input_artifact_sha256": "b" * 64,
        "label_version": "label-v1",
        "benchmark_id": "TAIEX",
        "benchmark_version": "benchmark-v1",
        "cost_profile_version": "cost-v1",
        "training_end_date": "2025-12-31",
        "model_metadata": {"rank_model": "LightGBM"},
        "cost_metadata": {
            "asset_type": "COMMON_STOCK",
            "commission_rate": 0.001425,
            "commission_discount": 1.0,
            "minimum_fee": 20.0,
            "sell_tax_rate": 0.003,
            "estimated_order_notional_ntd": 100000.0,
            "spread_model": "tick_liquidity_adv20_v1",
            "slippage_scenario": "base",
            "market_impact_parameter": 0.001,
            "max_adv_participation": 0.01,
        },
        "validation": {"fold_count": 1},
        "reason_codes": ["TWSE_PRICE_ONLY_RESEARCH"],
    }
    payload["snapshot_sha256"] = sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return payload


def test_staging_publish_is_conservative_and_idempotent() -> None:
    writer = _Writer()
    result = TwseResearchPredictionSupabasePublisher(
        writer,
        target_environment="staging",
        publish_enabled=True,
    ).publish(_payload())

    assert result.prediction_run_id == 7
    assert result.prediction_count == 1
    assert [value[0] for value in writer.upserts] == [
        "cost_profiles",
        "prediction_runs",
        "stock_predictions",
    ]
    run = writer.upserts[1][1][0]
    stock = writer.upserts[2][1][0]
    assert run["system_validation_status"] == "RESEARCH_ONLY"
    assert run["candidate_count"] == 0
    assert run["no_trade_count"] == 1
    assert stock["decision"] == "NO_TRADE"
    assert stock["data_quality_status"] == "FAIL"
    assert "RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY" in cast(
        list[object], stock["reason_codes"]
    )


@pytest.mark.parametrize("environment", ["", "prod"])
def test_publish_gate_rejects_unknown_environment(environment: str) -> None:
    with pytest.raises(ValueError, match="recognized environment"):
        _ = TwseResearchPredictionSupabasePublisher(
            _Writer(),
            target_environment=environment,
            publish_enabled=True,
        )


def test_production_publish_requires_a_second_explicit_gate() -> None:
    with pytest.raises(ValueError, match="PRODUCTION_PUBLISH_ENABLED"):
        _ = TwseResearchPredictionSupabasePublisher(
            _Writer(),
            target_environment="production",
            publish_enabled=True,
        )


def test_explicit_production_research_publish_remains_no_trade() -> None:
    writer = _Writer()
    result = TwseResearchPredictionSupabasePublisher(
        writer,
        target_environment="production",
        publish_enabled=True,
        production_publish_enabled=True,
    ).publish(_payload())

    assert result.target_environment == "production"
    run = writer.upserts[1][1][0]
    stock = writer.upserts[2][1][0]
    assert run["system_validation_status"] == "RESEARCH_ONLY"
    assert run["candidate_count"] == 0
    assert stock["decision"] == "NO_TRADE"
    assert "RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY" in cast(
        list[object], stock["reason_codes"]
    )


def test_publish_gate_is_disabled_by_default() -> None:
    with pytest.raises(ValueError, match="PUBLISH_ENABLED"):
        _ = TwseResearchPredictionSupabasePublisher(
            _Writer(),
            target_environment="staging",
            publish_enabled=False,
        )
