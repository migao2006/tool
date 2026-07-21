from datetime import date, datetime, timezone

import pytest

from src.api.prediction_output import StockPredictionOutput
from src.config import load_mvp_config
from src.core.horizon import require_production_horizon, require_supported_horizon
from src.features import load_feature_catalog


def test_horizon_interface_accepts_future_values_but_production_only_allows_five():
    assert require_supported_horizon(3) == 3
    assert require_production_horizon(5) == 5
    with pytest.raises(NotImplementedError):
        require_production_horizon(10)


def test_config_is_research_only_and_five_day():
    config = load_mvp_config()
    assert config.horizon == 5
    assert config.status == "RESEARCH_ONLY"
    assert config.rank.objective == "lambdarank"
    assert config.rank.eval_at == (10, 20, 50)


def test_feature_catalog_is_complete_and_unique():
    definitions = load_feature_catalog()
    assert len(definitions) >= 20
    assert len({item.name for item in definitions}) == len(definitions)
    assert all(item.available_at_rule for item in definitions)
    assert all(item.missing_policy for item in definitions)


def test_prediction_contract_rejects_probability_or_quantile_errors():
    common = dict(
        as_of_date=date(2026, 7, 17),
        decision_at=datetime(2026, 7, 17, 6, 0, tzinfo=timezone.utc),
        symbol="TEST",
        name="測試股票",
        market="LISTED",
        industry=None,
        horizon=5,
        rank_score=90.0,
        global_rank=1,
        global_rank_percentile=0.99,
        industry_rank=None,
        industry_rank_percentile=None,
        calibration_version="not-trained",
        gross_q10=-0.02,
        gross_q50=0.01,
        gross_q90=0.04,
        net_q10=-0.025,
        net_q50=0.005,
        net_q90=0.035,
        interval_width=0.06,
        calibration_status="RESEARCH_ONLY",
        forecast_volatility=None,
        downside_risk=None,
        market_regime=None,
        market_exposure_cap=0.0,
        estimated_round_trip_cost=0.005,
        data_quality_status="FAIL",
        decision="NO_TRADE",
        reason_codes=("NO_REAL_DATA",),
        model_version="not-trained",
        feature_schema_hash="not-trained",
        cost_profile_version="tw_stock_swing_v1",
        training_end_date=date(2026, 7, 16),
        source_dates={},
        latest_available_at=datetime(2026, 7, 17, 6, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError, match="sum to 1"):
        StockPredictionOutput(
            **common,
            calibrated_p_up=0.7,
            calibrated_p_neutral=0.3,
            calibrated_p_down=0.2,
        )
