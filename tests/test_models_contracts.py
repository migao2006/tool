from __future__ import annotations

import pytest

from src.models.market.market_model import classify_market_regime, market_exposure_cap
from src.models.risk.volatility_model import qlike, select_production_model
from src.models.stock.direction_model import (
    Direction,
    DirectionModel,
    NoTradeBandConfig,
    make_direction_label,
    no_trade_band,
)
from src.models.stock.quantile_return_model import QuantileReturnModel
from src.validation.model_metrics import macro_f1, pinball_loss, quantile_coverage, reliability_diagram


def test_dynamic_no_trade_band_and_direction_labels() -> None:
    config = NoTradeBandConfig(horizon=5, min_edge_h=0.01, k_h=0.5)
    band = no_trade_band(0.02, config)
    assert band > 0.01
    assert make_direction_label(band + 0.001, 0.02, config) == Direction.UP
    assert make_direction_label(-band - 0.001, 0.02, config) == Direction.DOWN
    assert make_direction_label(0.0, 0.02, config) == Direction.NEUTRAL


def test_direction_training_rejects_fold_missing_any_class() -> None:
    with pytest.raises(ValueError, match="missing classes"):
        DirectionModel(backend="logistic").fit([[0.0], [1.0]], [Direction.UP, Direction.DOWN])


def test_quantile_prediction_records_crossing_before_reorder() -> None:
    class StubModel:
        def __init__(self, values: list[float]) -> None:
            self.values = values

        def predict(self, _features: object) -> list[float]:
            return self.values

    model = QuantileReturnModel(horizon=5)
    model.models = {0.10: StubModel([0.03]), 0.50: StubModel([0.01]), 0.90: StubModel([0.02])}
    prediction = model.predict([[1.0]], 0.005)[0]
    assert prediction.raw_crossed is True
    assert prediction.gross_q10 <= prediction.gross_q50 <= prediction.gross_q90
    assert prediction.net_q50 == pytest.approx(prediction.gross_q50 - 0.005)


def test_market_regime_is_trailing_rule_and_exposure_is_bounded() -> None:
    assert classify_market_regime(0.01, 0.01, 0.6) == "UPTREND_LOW_VOL_BROAD"
    exposure = market_exposure_cap(
        {"UP": 0.7, "NEUTRAL": 0.2, "DOWN": 0.1},
        forecast_market_volatility=0.2,
        target_volatility=0.1,
        maximum_exposure=0.8,
    )
    assert exposure == pytest.approx(0.32)


def test_volatility_candidate_falls_back_unless_it_wins_most_folds() -> None:
    results = {"lightgbm": [0.8, 1.3, 1.2], "ewma": [1.0, 1.0, 1.0], "har": [0.9, 1.1, 1.1]}
    assert select_production_model(results) == "ewma"
    assert qlike(1.0, 1.0) == pytest.approx(0.0)


def test_direction_and_quantile_metrics_are_not_accuracy_only() -> None:
    assert macro_f1(["UP", "NEUTRAL", "DOWN"], ["UP", "NEUTRAL", "DOWN"]) == pytest.approx(1.0)
    assert pinball_loss([0.0, 0.1], [0.0, 0.0], 0.5) == pytest.approx(0.025)
    coverage = quantile_coverage([0.0, 0.2], [-0.1, -0.1], [0.1, 0.1])
    assert coverage["p90_exceedance_rate"] == 0.5
    assert sum(item.sample_count for item in reliability_diagram([0.1, 0.9], [False, True])) == 2
