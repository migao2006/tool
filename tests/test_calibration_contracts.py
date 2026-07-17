from __future__ import annotations

import pytest

from src.calibration.interval_calibrator import IntervalCalibrator, crossing_rate, reorder_quantiles
from src.calibration.probability_calibrator import ProbabilityCalibrator, classwise_brier_score


def test_probability_calibration_is_disjoint_and_sums_to_one() -> None:
    probabilities = [
        {"UP": 0.8, "NEUTRAL": 0.1, "DOWN": 0.1},
        {"UP": 0.2, "NEUTRAL": 0.7, "DOWN": 0.1},
        {"UP": 0.1, "NEUTRAL": 0.2, "DOWN": 0.7},
    ]
    calibrator = ProbabilityCalibrator(method="temperature").fit(
        probabilities,
        ["UP", "NEUTRAL", "DOWN"],
        calibration_ids=["c1", "c2", "c3"],
        base_training_ids=["t1", "t2"],
    )
    calibrated = calibrator.transform_named(probabilities)
    assert sum(calibrated[0].values()) == pytest.approx(1.0)
    assert calibrator.audit is not None


def test_probability_calibration_rejects_training_overlap() -> None:
    with pytest.raises(ValueError, match="disjoint"):
        ProbabilityCalibrator().fit(
            [[0.8, 0.1, 0.1]],
            ["UP"],
            calibration_ids=["same"],
            base_training_ids=["same"],
        )


def test_classwise_brier_is_reported_independently() -> None:
    scores = classwise_brier_score([[0.8, 0.1, 0.1]], ["UP"])
    assert set(scores) == {"UP", "NEUTRAL", "DOWN"}


def test_interval_calibrator_audits_raw_crossing_and_returns_monotonic_output() -> None:
    calibrator = IntervalCalibrator().fit(
        y_true=[0.0, 0.1, -0.1],
        q10=[0.03, 0.02, -0.05],
        q50=[0.01, 0.05, 0.0],
        q90=[0.02, 0.08, 0.05],
        calibration_ids=["c1", "c2", "c3"],
        base_training_ids=["t1", "t2"],
    )
    q10, q50, q90, raw_crossed = calibrator.transform_one(0.03, 0.01, 0.02)
    assert raw_crossed is True
    assert q10 <= q50 <= q90
    assert calibrator.audit is not None
    assert calibrator.audit.raw_crossing_rate > 0
    assert calibrator.audit.calibrated_crossing_rate == 0
    assert reorder_quantiles(3, 1, 2) == (1.0, 2.0, 3.0)
    assert crossing_rate([(1, 3, 2)]) == 1.0
