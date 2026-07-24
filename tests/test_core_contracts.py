from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from src.api.market_output import MarketOutput
from src.api.prediction_output import DecisionGateOutput, StockPredictionOutput
from src.config import load_mvp_config
from src.core.horizon import require_production_horizon, require_supported_horizon
from src.features import load_feature_catalog
from src.models.metadata import ModelMetadata
from tests.support.policy_evidence import required_policy_evidence


def test_mvp_config_is_five_day_research_only() -> None:
    config = load_mvp_config()
    assert config.horizon == 5
    assert config.status == "RESEARCH_ONLY"
    assert config.rank.objective == "lambdarank"
    assert config.rank.eval_at == (10, 20, 50)
    assert config.cost.profile_version == "tw_stock_swing_v1"
    assert config.cost.market_impact_parameter == 0.001


def test_horizon_interfaces_are_extensible_but_production_is_five_only() -> None:
    assert require_supported_horizon(3) == 3
    assert require_supported_horizon(10) == 10
    assert require_production_horizon(5) == 5
    with pytest.raises(NotImplementedError):
        require_production_horizon(3)
    with pytest.raises(ValueError):
        require_supported_horizon(7)


def test_feature_catalog_has_auditable_fields_and_no_duplicates() -> None:
    catalog = load_feature_catalog()
    names = {item.name for item in catalog}
    assert len(catalog) == len(names)
    assert {"total_return_5d", "foreign_net_ratio_5", "us_market_last_available_return"} <= names
    assert all(item.formula and item.source and item.available_at_rule for item in catalog)
    assert all(item.missing_policy for item in catalog)


def test_prediction_output_rejects_non_monotonic_quantiles() -> None:
    with pytest.raises(ValueError, match="net quantiles"):
        _prediction(net_q10=0.02, net_q50=0.01, net_q90=0.03)


def test_prediction_output_contains_no_ev_or_final_score() -> None:
    payload = _prediction().to_dict()
    assert payload["horizon"] == 5
    assert "expected_return" not in payload
    assert "ev" not in payload
    assert "final_score" not in payload
    assert "model_raw_score" not in payload


def test_candidate_output_requires_oos_calibration_and_valid_audit_fields() -> None:
    research_output = _prediction()
    with pytest.raises(ValueError, match="calibrated return intervals"):
        replace(research_output, decision="CANDIDATE", reason_codes=())

    candidate = replace(
        research_output,
        decision="CANDIDATE",
        calibration_status="CALIBRATED:interval-cal-v1",
        reason_codes=(),
    )
    assert candidate.decision == "CANDIDATE"

    with pytest.raises(ValueError, match="non-negative"):
        replace(research_output, estimated_round_trip_cost=-0.001)
    with pytest.raises(ValueError, match="source date"):
        replace(research_output, source_dates={"daily_bars": "2026-01-03"})


def test_market_output_rejects_future_model_or_invalid_risk_fields() -> None:
    common = dict(
        as_of_date=date(2026, 1, 2),
        decision_at=datetime(2026, 1, 2, 10, tzinfo=timezone.utc),
        horizon=5,
        p_up=0.6,
        p_neutral=0.3,
        p_down=0.1,
        market_regime="UPTREND_LOW_VOL_BROAD",
        forecast_market_volatility=0.02,
        market_exposure_cap=0.6,
        model_version="market-v1",
        training_end_date=date(2025, 12, 31),
    )
    assert MarketOutput(**common).market_exposure_cap == 0.6

    with pytest.raises(ValueError, match="earlier than as_of_date"):
        MarketOutput(**{**common, "training_end_date": date(2026, 1, 2)})
    with pytest.raises(ValueError, match="non-negative"):
        MarketOutput(**{**common, "forecast_market_volatility": -0.01})


def test_model_metadata_is_saved_per_horizon(tmp_path) -> None:
    metadata = ModelMetadata(
        model_family="RANK",
        horizon=5,
        model_version="rank-5d-research-v1",
        feature_schema_hash="schema-hash",
        training_end_date=date(2025, 12, 31),
        benchmark_version="TWSE_TAIEX_V1",
        cost_profile_version="tw_stock_swing_v1",
        validation_status="RESEARCH_ONLY",
        artifact_filename="rank_model.txt",
    )
    target = metadata.save(tmp_path)
    assert target == tmp_path / "horizon_5" / "rank" / "metadata.json"
    assert target.exists()
    assert metadata.eligible_at(datetime.now(timezone.utc)) is True
    assert metadata.eligible_at(datetime(2025, 1, 1, tzinfo=timezone.utc)) is False


def _prediction(**overrides: float) -> StockPredictionOutput:
    values = {
        "net_q10": -0.03,
        "net_q50": 0.01,
        "net_q90": 0.05,
    }
    values.update(overrides)
    decision_at = datetime(2026, 1, 2, 10, tzinfo=timezone.utc)
    as_of_date = date(2026, 1, 2)
    gate_names = (
        "data_quality_hard_gate",
        "tradability_gate",
        "liquidity_capacity_gate",
        "market_exposure_cap",
        "calibrated_direction_probabilities",
        "net_quantile_thresholds",
        "rank_eligibility",
        "position_capacity_limits",
    )
    gates = tuple(
        DecisionGateOutput(
            gate=name,
            passed=True,
            actual=evidence["value"] if evidence is not None else "PASS",
            threshold="PASS",
            reason_code="PASS",
            source_date=as_of_date,
            evidence=evidence,
        )
        for name in gate_names
        for evidence in (
            required_policy_evidence(
                name,
                as_of_date=as_of_date,
                decision_at=decision_at,
                symbol="TEST",
                market_regime="RANGE_NORMAL_VOL",
                market_exposure_cap=0.5,
            ),
        )
    )
    return StockPredictionOutput(
        as_of_date=as_of_date,
        decision_at=decision_at,
        symbol="TEST",
        name="測試股票",
        market="LISTED",
        industry="TEST_ONLY",
        horizon=5,
        rank_score=90.0,
        global_rank=1,
        global_rank_percentile=0.99,
        industry_rank=1,
        industry_rank_percentile=0.98,
        calibrated_p_up=0.6,
        calibrated_p_neutral=0.25,
        calibrated_p_down=0.15,
        calibration_version="cal-v1",
        gross_q10=-0.02,
        gross_q50=0.02,
        gross_q90=0.06,
        net_q10=values["net_q10"],
        net_q50=values["net_q50"],
        net_q90=values["net_q90"],
        interval_width=0.08,
        calibration_status="RESEARCH_ONLY",
        forecast_volatility=0.03,
        downside_risk=0.02,
        market_regime="RANGE_NORMAL_VOL",
        market_exposure_cap=0.5,
        max_single_position=0.1,
        max_industry_position=0.25,
        estimated_round_trip_cost=0.006,
        data_quality_status="PASS",
        decision="WATCH",
        decision_policy_status="EVALUATED",
        reason_codes=("RESEARCH_ONLY", "OUTSIDE_TOP_K"),
        model_version="bundle-v1",
        feature_schema_hash="schema-hash",
        cost_profile_version="tw_stock_swing_v1",
        training_end_date=date(2025, 12, 31),
        source_dates={"daily_bars": "2026-01-02"},
        latest_available_at=decision_at,
        gates=gates,
    )
