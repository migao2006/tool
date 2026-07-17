from __future__ import annotations

from datetime import date, datetime, timezone
import json

import pytest

from src.api import (
    API_CONTRACT_VERSION,
    DecisionGateOutput,
    ExcludedSecurityOutput,
    MarketOutput,
    PredictionSnapshotOutput,
    StockPredictionOutput,
)


AS_OF_DATE = date(2026, 7, 17)
DECISION_AT = datetime(2026, 7, 17, 6, 0, tzinfo=timezone.utc)
TRAINING_END_DATE = date(2026, 6, 30)


def _gates() -> tuple[DecisionGateOutput, ...]:
    names = (
        "data_quality_hard_gate",
        "tradability_gate",
        "liquidity_capacity_gate",
        "market_exposure_cap",
        "calibrated_direction_probabilities",
        "net_quantile_thresholds",
        "rank_eligibility",
        "position_capacity_limits",
    )
    return tuple(
        DecisionGateOutput(
            gate=name,
            passed=True,
            actual="PASS",
            threshold="PASS",
            reason_code="PASS",
        )
        for name in names
    )


def _prediction() -> StockPredictionOutput:
    return StockPredictionOutput(
        as_of_date=AS_OF_DATE,
        decision_at=DECISION_AT,
        symbol="TEST",
        name="測試股票",
        market="LISTED",
        industry="TEST_INDUSTRY",
        horizon=5,
        rank_score=95.0,
        global_rank=1,
        global_rank_percentile=0.99,
        industry_rank=1,
        industry_rank_percentile=0.98,
        calibrated_p_up=0.65,
        calibrated_p_neutral=0.25,
        calibrated_p_down=0.10,
        calibration_version="direction-cal-v1",
        gross_q10=-0.02,
        gross_q50=0.02,
        gross_q90=0.05,
        net_q10=-0.03,
        net_q50=0.01,
        net_q90=0.03,
        interval_width=0.06,
        calibration_status="CALIBRATED:quantile-cal-v1",
        forecast_volatility=0.03,
        downside_risk=0.02,
        market_regime="UPTREND_NORMAL_VOL",
        market_exposure_cap=0.6,
        estimated_round_trip_cost=0.01,
        data_quality_status="PASS",
        decision="CANDIDATE",
        reason_codes=(),
        model_version="rank-5d-v1",
        feature_schema_hash="schema-sha256-v1",
        cost_profile_version="tw-stock-base-v1",
        training_end_date=TRAINING_END_DATE,
        source_dates={"daily_bars": AS_OF_DATE},
        latest_available_at=DECISION_AT,
        liquidity_bucket="LARGE_LIQUID",
        adv20=1_000_000_000.0,
        max_order_notional_ntd=10_000_000.0,
        max_single_position=0.10,
        max_industry_position=0.25,
        cost_profile="base_cost",
        previous_global_rank=3,
        previous_decision="WATCH",
        gates=_gates(),
    )


def _market() -> MarketOutput:
    return MarketOutput(
        as_of_date=AS_OF_DATE,
        decision_at=DECISION_AT,
        horizon=5,
        p_up=0.60,
        p_neutral=0.25,
        p_down=0.15,
        market_regime="UPTREND_NORMAL_VOL",
        forecast_market_volatility=0.18,
        market_exposure_cap=0.60,
        model_version="market-5d-v1",
        training_end_date=TRAINING_END_DATE,
    )


def test_snapshot_serializes_the_versioned_frontend_contract() -> None:
    prediction = _prediction()
    snapshot = PredictionSnapshotOutput(
        as_of_date=AS_OF_DATE,
        decision_at=DECISION_AT,
        horizon=5,
        system_status="PASS",
        market=_market(),
        predictions=(prediction,),
        watchlist=(prediction,),
        excluded=(
            ExcludedSecurityOutput(
                as_of_date=AS_OF_DATE,
                symbol="FAIL1",
                name="排除股票",
                market="OTC",
                horizon=5,
                reason_codes=("DATA_QUALITY_HARD_FAIL",),
                latest_available_at=DECISION_AT,
            ),
        ),
        model_version="rank-5d-v1",
        training_end_date=TRAINING_END_DATE,
        cost_profile_version="tw-stock-base-v1",
        validation={"ndcg_10": 0.42, "known_limitations": ["locked holdout pending"]},
    )

    payload = snapshot.to_dict()

    assert payload["api_contract_version"] == API_CONTRACT_VERSION
    assert payload["market"]["p_up"] == pytest.approx(0.60)
    assert payload["predictions"][0]["name"] == "測試股票"
    assert payload["predictions"][0]["gates"][0]["gate"] == "data_quality_hard_gate"
    assert payload["excluded"][0]["data_quality_hard_fail"] is True
    json.dumps(payload, ensure_ascii=False, allow_nan=False)


def test_pass_snapshot_rejects_missing_detail_contract_or_non_finite_metrics() -> None:
    prediction = _prediction()
    incomplete = StockPredictionOutput(
        **{
            **prediction.__dict__,
            "gates": (),
        }
    )
    with pytest.raises(ValueError, match="missing API detail fields"):
        PredictionSnapshotOutput(
            as_of_date=AS_OF_DATE,
            decision_at=DECISION_AT,
            horizon=5,
            system_status="PASS",
            market=_market(),
            predictions=(incomplete,),
            model_version="rank-5d-v1",
            training_end_date=TRAINING_END_DATE,
            cost_profile_version="tw-stock-base-v1",
            validation={"ndcg_10": 0.42},
        )

    with pytest.raises(ValueError, match="NaN or infinity"):
        PredictionSnapshotOutput(
            as_of_date=AS_OF_DATE,
            decision_at=DECISION_AT,
            horizon=5,
            system_status="RESEARCH_ONLY",
            validation={"ndcg_10": float("nan")},
        )


def test_pass_snapshot_rejects_stale_or_inconsistent_market_output() -> None:
    prediction = _prediction()
    with pytest.raises(ValueError, match="cannot be stale"):
        PredictionSnapshotOutput(
            as_of_date=AS_OF_DATE,
            decision_at=DECISION_AT,
            horizon=5,
            system_status="PASS",
            stale=True,
            market=_market(),
            predictions=(prediction,),
            model_version="rank-5d-v1",
            training_end_date=TRAINING_END_DATE,
            cost_profile_version="tw-stock-base-v1",
            validation={"ndcg_10": 0.42},
        )

    inconsistent = StockPredictionOutput(
        **{
            **prediction.__dict__,
            "market_exposure_cap": 0.5,
        }
    )
    with pytest.raises(ValueError, match="market_exposure_cap"):
        PredictionSnapshotOutput(
            as_of_date=AS_OF_DATE,
            decision_at=DECISION_AT,
            horizon=5,
            system_status="PASS",
            market=_market(),
            predictions=(inconsistent,),
            model_version="rank-5d-v1",
            training_end_date=TRAINING_END_DATE,
            cost_profile_version="tw-stock-base-v1",
            validation={"ndcg_10": 0.42},
        )


def test_candidate_output_rejects_failed_decision_gate() -> None:
    prediction = _prediction()
    failed_gates = (
        *prediction.gates[:-1],
        DecisionGateOutput(
            gate="position_capacity_limits",
            passed=False,
            actual=False,
            threshold=True,
            reason_code="POSITION_LIMIT_FAIL",
        ),
    )
    with pytest.raises(ValueError, match="failed decision gate"):
        StockPredictionOutput(**{**prediction.__dict__, "gates": failed_gates})
