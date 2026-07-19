from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import median
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from src.data.preprocessing import CrossSectionalMedianImputer, FoldFitScope
from src.pipeline.twse_research_fold_preparation import prepare_fold


TAIPEI = ZoneInfo("Asia/Taipei")


def _scope() -> FoldFitScope:
    return FoldFitScope(
        "scale-test-fold",
        datetime(2025, 12, 31, 17, tzinfo=TAIPEI),
    )


def _reference_transform(
    rows: list[dict[str, float | None]],
    decision_dates: list[date],
    *,
    feature_names: tuple[str, ...],
    fallbacks: dict[str, float],
) -> list[dict[str, float]]:
    grouped: dict[date, list[int]] = {}
    for index, decision_date in enumerate(decision_dates):
        grouped.setdefault(decision_date, []).append(index)
    medians: dict[tuple[date, str], float] = {}
    for decision_date, indices in grouped.items():
        for name in feature_names:
            values = [
                float(rows[index][name])
                for index in indices
                if rows[index].get(name) is not None
            ]
            medians[(decision_date, name)] = (
                median(values) if values else fallbacks[name]
            )
    output: list[dict[str, float]] = []
    for row, decision_date in zip(rows, decision_dates):
        transformed: dict[str, float] = {}
        for name in feature_names:
            missing = row.get(name) is None
            transformed[name] = (
                medians[(decision_date, name)] if missing else float(row[name])
            )
            transformed[f"{name}__missing"] = float(missing)
        output.append(transformed)
    return output


def test_array_and_mapping_paths_match_cross_sectional_reference() -> None:
    names = ("x", "y")
    available_ats = (
        datetime(2025, 1, 1, 17, tzinfo=TAIPEI),
        datetime(2025, 1, 2, 17, tzinfo=TAIPEI),
        datetime(2025, 1, 3, 17, tzinfo=TAIPEI),
    )
    imputer = CrossSectionalMedianImputer().fit(
        (
            {"x": 1.0, "y": 2.0},
            {"x": 3.0, "y": 4.0},
            {"x": 8.0, "y": 10.0},
        ),
        feature_names=names,
        scope=_scope(),
        row_available_ats=available_ats,
    )
    first = date(2026, 1, 5)
    second = date(2026, 1, 6)
    third = date(2026, 1, 7)
    dates = [first, second, first, second, third, third]
    rows = [
        {"x": 1.0, "y": None},
        {"x": None, "y": None},
        {"x": None, "y": 5.0},
        {"x": 9.0, "y": None},
        {"x": None, "y": 3.0},
        {"x": None, "y": 7.0},
    ]
    expected = _reference_transform(
        rows,
        dates,
        feature_names=names,
        fallbacks={"x": 3.0, "y": 4.0},
    )

    assert imputer.transform(rows, decision_dates=dates) == expected
    matrix = np.asarray([[row[name] for name in names] for row in rows], dtype=float)
    transformed = imputer.transform_array(
        matrix,
        decision_dates=dates,
        output_dtype=np.float64,
    )
    np.testing.assert_array_equal(
        transformed,
        pd.DataFrame(expected).to_numpy(),
    )


def test_frame_path_is_float32_and_does_not_leak_between_dates() -> None:
    train = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    imputer = CrossSectionalMedianImputer().fit_frame(
        train,
        feature_names=("x",),
        scope=_scope(),
        row_available_ats=pd.Series(
            pd.to_datetime(
                [
                    "2025-01-01T09:00:00Z",
                    "2025-01-02T09:00:00Z",
                    "2025-01-03T09:00:00Z",
                ],
                utc=True,
            )
        ),
    )
    first = date(2026, 1, 5)
    second = date(2026, 1, 6)
    inference = pd.DataFrame({"x": [100.0, np.nan, np.nan]})

    transformed = imputer.transform_frame(
        inference,
        decision_dates=(first, first, second),
    )

    assert transformed.columns.tolist() == ["x", "x__missing"]
    assert transformed.dtypes.tolist() == [np.dtype("float32"), np.dtype("float32")]
    assert transformed.to_dict(orient="records") == [
        {"x": 100.0, "x__missing": 0.0},
        {"x": 100.0, "x__missing": 1.0},
        {"x": 2.0, "x__missing": 1.0},
    ]
    repeated = imputer.transform_frame(
        pd.DataFrame({"x": [np.nan]}),
        decision_dates=(date(2026, 1, 8),),
    )
    assert repeated.iloc[0].to_dict() == {"x": 2.0, "x__missing": 1.0}


def test_transform_rejects_missing_decision_date_even_without_missing_features() -> (
    None
):
    imputer = CrossSectionalMedianImputer().fit(
        ({"x": 1.0},),
        feature_names=("x",),
        scope=_scope(),
        row_available_ats=(datetime(2025, 1, 1, 17, tzinfo=TAIPEI),),
    )

    with pytest.raises(ValueError, match="decision_dates"):
        imputer.transform_array(
            np.asarray([[1.0]]),
            decision_dates=np.asarray([None], dtype=object),
        )


def test_frame_fit_rejects_post_training_availability() -> None:
    with pytest.raises(ValueError, match="training end"):
        CrossSectionalMedianImputer().fit_frame(
            pd.DataFrame({"x": [1.0]}),
            feature_names=("x",),
            scope=_scope(),
            row_available_ats=pd.Series(
                pd.to_datetime(["2026-01-01T09:00:00Z"], utc=True)
            ),
        )


def test_prepare_fold_bypasses_record_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = datetime(2025, 1, 1, 17, tzinfo=TAIPEI)
    frame = pd.DataFrame(
        {
            "decision_date": [
                date(2025, 1, 1) + timedelta(days=i // 2) for i in range(8)
            ],
            "decision_at": [
                pd.Timestamp(base + timedelta(days=i // 2)) for i in range(8)
            ],
            "available_at": [
                pd.Timestamp(base + timedelta(days=i // 2)) for i in range(8)
            ],
            "x": [1.0, 3.0, 4.0, np.nan, 8.0, np.nan, 10.0, np.nan],
            "y": [2.0, 6.0, np.nan, 8.0, np.nan, np.nan, 12.0, 14.0],
        }
    )
    dataset = SimpleNamespace(frame=frame, feature_names=("x", "y"))

    def reject_record_path(*args: object, **kwargs: object) -> None:
        raise AssertionError("record-oriented preprocessing must not be used")

    monkeypatch.setattr(CrossSectionalMedianImputer, "fit", reject_record_path)
    monkeypatch.setattr(CrossSectionalMedianImputer, "transform", reject_record_path)

    matrices = prepare_fold(
        dataset,
        train_indices=(0, 1, 2, 3),
        calibration_indices=(4, 5),
        test_indices=(6, 7),
        fold_number=1,
    )

    assert matrices.train.shape == (4, 4)
    assert matrices.calibration.shape == (2, 4)
    assert matrices.test.shape == (2, 4)
    assert matrices.test.dtypes.eq(np.dtype("float32")).all()
    assert matrices.calibration["y"].tolist() == [6.0, 6.0]
    assert matrices.calibration["y__missing"].tolist() == [1.0, 1.0]


def test_large_array_path_preserves_shape_dtype_and_fallbacks() -> None:
    row_count = 120_000
    feature_count = 17
    group_size = 600
    rng = np.random.default_rng(20260719)
    train_values = rng.standard_normal((10_000, feature_count))
    fit_times = pd.Series(
        pd.to_datetime(["2025-01-01T09:00:00Z"] * len(train_values), utc=True)
    )
    names = tuple(f"feature_{index}" for index in range(feature_count))
    imputer = CrossSectionalMedianImputer().fit_array(
        train_values,
        feature_names=names,
        scope=_scope(),
        row_available_ats=fit_times,
    )
    values = rng.standard_normal((row_count, feature_count)).astype(np.float32)
    values[::23, :] = np.nan
    values[:group_size, 0] = np.nan
    start = date(2025, 1, 1)
    decision_dates = np.repeat(
        np.asarray(
            [start + timedelta(days=index) for index in range(row_count // group_size)],
            dtype=object,
        ),
        group_size,
    )

    transformed = imputer.transform_array(
        values,
        decision_dates=decision_dates,
    )

    assert transformed.shape == (row_count, feature_count * 2)
    assert transformed.dtype == np.float32
    assert not np.isnan(transformed[:, 0::2]).any()
    assert np.all(transformed[:group_size, 1] == 1.0)
