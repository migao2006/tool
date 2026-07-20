from __future__ import annotations

# pyright: reportAny=false, reportMissingTypeStubs=false

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import numpy as np
import pandas as pd
import pytest

from src.calibration.interval_calibrator import IntervalCalibrator
from src.calibration.probability_calibrator import ProbabilityCalibrator
from src.data.preprocessing import CrossSectionalMedianImputer, FoldFitScope
from src.pipeline.twse_research_model_bundle_contracts import (
    BUNDLE_FILE_NAMES,
    TPEX_RESEARCH_BUNDLE_CONTRACT_VERSION,
)
from src.pipeline.twse_research_model_bundle_io import (
    FittedBundleComponents,
    TwseResearchBundleReader,
    TwseResearchBundleWriter,
)


UTC = timezone.utc


def _fitted_components():
    lightgbm = pytest.importorskip("lightgbm")
    raw = pd.DataFrame(
        {
            "momentum": [-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
            "liquidity": [1.0, 1.1, 0.9, 1.2, 1.3, 1.1, 1.4, 1.5, 1.6],
        }
    )
    fit_at = datetime(2024, 1, 31, 6, 30, tzinfo=UTC)
    imputer = CrossSectionalMedianImputer().fit_frame(
        raw,
        feature_names=("momentum", "liquidity"),
        scope=FoldFitScope("twse-research-fold-4", fit_at),
        row_available_ats=[fit_at] * len(raw),
    )
    matrix = imputer.transform_frame(
        raw, decision_dates=[date(2024, 1, 31)] * len(raw)
    )
    common = {"n_estimators": 4, "num_leaves": 4, "verbosity": -1, "random_state": 7}
    rank = lightgbm.LGBMRegressor(**common).fit(
        matrix, np.linspace(-0.1, 0.1, len(matrix))
    )
    labels = ["DOWN", "NEUTRAL", "UP"] * 3
    direction = lightgbm.LGBMClassifier(
        objective="multiclass", num_class=3, **common
    ).fit(matrix, labels)
    quantiles = {
        alpha: lightgbm.LGBMRegressor(
            objective="quantile", alpha=alpha, **common
        ).fit(matrix, np.linspace(-0.08, 0.12, len(matrix)))
        for alpha in (0.10, 0.50, 0.90)
    }
    raw_calibration = [
        {"UP": 0.2, "NEUTRAL": 0.3, "DOWN": 0.5},
        {"UP": 0.3, "NEUTRAL": 0.5, "DOWN": 0.2},
        {"UP": 0.6, "NEUTRAL": 0.2, "DOWN": 0.2},
    ]
    probability = ProbabilityCalibrator(method="temperature").fit(
        raw_calibration,
        ["DOWN", "NEUTRAL", "UP"],
        calibration_ids=("c1", "c2", "c3"),
        base_training_ids=("t1", "t2", "t3"),
    )
    interval = IntervalCalibrator().fit(
        (-0.03, 0.01, 0.06),
        (-0.05, -0.01, 0.02),
        (-0.01, 0.02, 0.05),
        (0.03, 0.06, 0.09),
        calibration_ids=("c1", "c2", "c3"),
        base_training_ids=("t1", "t2", "t3"),
    )
    components = SimpleNamespace(
        imputer=imputer,
        rank_model=SimpleNamespace(model=rank),
        direction_model=SimpleNamespace(model=direction),
        probability_calibrator=probability,
        quantile_model=SimpleNamespace(models=quantiles),
        interval_calibrator=interval,
    )
    return components, raw, matrix


def _write_bundle(tmp_path: Path):
    components, raw, matrix = _fitted_components()
    bundle_dir = tmp_path / "twse-bundle"
    written = TwseResearchBundleWriter().write(
        bundle_dir,
        components=cast(FittedBundleComponents, cast(object, components)),
        model_version="twse-price-research-h5-v1",
        horizon=5,
        fold_number=4,
        feature_schema_hash="f" * 64,
        input_artifact_sha256="a" * 64,
        provenance={
            "dataset_snapshot_id": "snapshot-v1",
            "source_hash": "b" * 64,
            "label_version": "label-v1",
            "benchmark_id": "TAIEX",
            "benchmark_version": "benchmark-v1",
            "cost_profile_version": "cost-v1",
        },
        random_seed=7,
        feature_names=("momentum", "liquidity"),
        direction_classes=tuple(str(value) for value in components.direction_model.model.classes_),
        training_dates=(date(2024, 1, 1), date(2024, 1, 31)),
        calibration_dates=(date(2024, 2, 15), date(2024, 2, 29)),
        evaluated_test_dates=(date(2024, 3, 15), date(2024, 3, 29)),
        library_versions={"lightgbm": "test", "scikit-learn": "test"},
        reason_codes=(
            "MECHANICAL_LAST_WALK_FORWARD_FOLD",
            "LOCKED_HOLDOUT_NOT_EXECUTED",
        ),
        git_commit=None,
    )
    return written, components, raw, matrix


def test_native_bundle_round_trip_preserves_predictions(tmp_path: Path) -> None:
    written, components, raw, matrix = _write_bundle(tmp_path)

    loaded = TwseResearchBundleReader.read(written.bundle_dir)
    transformed = loaded.transform(
        raw, decision_dates=[date(2026, 7, 17)] * len(raw)
    )

    np.testing.assert_allclose(transformed.to_numpy(), matrix.to_numpy())
    np.testing.assert_allclose(
        loaded.predict_rank(matrix),
        components.rank_model.model.predict(matrix),
    )
    expected_direction = components.probability_calibrator.transform_rows(
        components.direction_model.model.predict_proba(matrix)
        [:, [2, 1, 0]]
    )
    actual_direction = loaded.predict_direction(matrix)
    np.testing.assert_allclose(
        [(row.up, row.neutral, row.down) for row in actual_direction],
        expected_direction,
    )
    quantiles = loaded.predict_quantiles(matrix)
    assert len(quantiles) == len(matrix)
    assert all(row.gross_q10 <= row.gross_q50 <= row.gross_q90 for row in quantiles)
    assert loaded.manifest.locked_holdout_executed is False
    assert loaded.manifest.selection_policy == "MECHANICAL_LAST_WALK_FORWARD_FOLD"
    assert set(path.name for path in written.bundle_dir.iterdir()) == {
        *BUNDLE_FILE_NAMES.values(),
        "manifest.json",
    }
    assert not any(path.suffix in {".pkl", ".pickle", ".joblib"} for path in written.bundle_dir.iterdir())


def test_manifest_identity_ignores_non_identity_creation_time(
    tmp_path: Path,
) -> None:
    written, _, _, _ = _write_bundle(tmp_path)
    later_copy = replace(
        written.manifest,
        created_at=written.manifest.created_at + timedelta(hours=1),
    )

    assert later_copy.created_at != written.manifest.created_at
    assert later_copy.to_dict()["created_at"] != written.manifest.to_dict()["created_at"]
    assert later_copy.manifest_sha256 == written.manifest.manifest_sha256


def test_manifest_identity_still_covers_fitted_artifact_content(
    tmp_path: Path,
) -> None:
    written, _, _, _ = _write_bundle(tmp_path)
    changed_file = replace(
        written.manifest.files["rank_booster"],
        sha256="0" * 64,
    )
    changed_manifest = replace(
        written.manifest,
        files={**written.manifest.files, "rank_booster": changed_file},
    )

    assert changed_manifest.manifest_sha256 != written.manifest.manifest_sha256


def test_bundle_reader_fails_closed_after_native_model_tampering(
    tmp_path: Path,
) -> None:
    written, _, _, _ = _write_bundle(tmp_path)
    rank_path = written.bundle_dir / BUNDLE_FILE_NAMES["rank_booster"]
    _ = rank_path.write_bytes(rank_path.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="hash mismatch"):
        _ = TwseResearchBundleReader.read(written.bundle_dir)


def test_bundle_directory_is_immutable(tmp_path: Path) -> None:
    written, components, _, _ = _write_bundle(tmp_path)

    with pytest.raises(FileExistsError, match="immutable"):
        _ = TwseResearchBundleWriter().write(
            written.bundle_dir,
            components=cast(FittedBundleComponents, cast(object, components)),
            model_version="twse-price-research-h5-v1",
            horizon=5,
            fold_number=4,
            feature_schema_hash="f" * 64,
            input_artifact_sha256="a" * 64,
            provenance={
                "dataset_snapshot_id": "snapshot-v1",
                "source_hash": "b" * 64,
                "label_version": "label-v1",
                "benchmark_id": "TAIEX",
                "benchmark_version": "benchmark-v1",
                "cost_profile_version": "cost-v1",
            },
            random_seed=7,
            feature_names=("momentum", "liquidity"),
            direction_classes=("DOWN", "NEUTRAL", "UP"),
            training_dates=(date(2024, 1, 1),),
            calibration_dates=(date(2024, 2, 1),),
            evaluated_test_dates=(date(2024, 3, 1),),
            library_versions={"lightgbm": "test"},
            reason_codes=("RESEARCH_ONLY",),
        )


def test_tpex_bundle_has_explicit_market_identity_and_cannot_load_as_twse(
    tmp_path: Path,
) -> None:
    components, raw, _ = _fitted_components()
    fit_at = datetime(2024, 1, 31, 6, 30, tzinfo=UTC)
    components.imputer = CrossSectionalMedianImputer().fit_frame(
        raw,
        feature_names=("momentum", "liquidity"),
        scope=FoldFitScope("tpex-research-fold-4", fit_at),
        row_available_ats=[fit_at] * len(raw),
    )
    written = TwseResearchBundleWriter().write(
        tmp_path / "tpex-bundle",
        components=cast(FittedBundleComponents, cast(object, components)),
        model_version="tpex-price-research-h5-v1",
        horizon=5,
        fold_number=4,
        feature_schema_hash="e" * 64,
        input_artifact_sha256="a" * 64,
        provenance={
            "dataset_snapshot_id": "snapshot-tpex-v1",
            "source_hash": "b" * 64,
            "label_version": "tpex-label-v1",
            "benchmark_id": "TPEX_PRICE_INDEX",
            "benchmark_version": "benchmark-v1",
            "cost_profile_version": "cost-v1",
        },
        random_seed=7,
        feature_names=("momentum", "liquidity"),
        direction_classes=tuple(
            str(value) for value in components.direction_model.model.classes_
        ),
        training_dates=(date(2024, 1, 1), date(2024, 1, 31)),
        calibration_dates=(date(2024, 2, 15), date(2024, 2, 29)),
        evaluated_test_dates=(date(2024, 3, 15), date(2024, 3, 29)),
        library_versions={"lightgbm": "test", "scikit-learn": "test"},
        reason_codes=("TPEX_PRICE_ONLY_RESEARCH",),
        market="TPEX",
    )

    loaded = TwseResearchBundleReader.read(
        written.bundle_dir, expected_market="TPEX"
    )
    assert loaded.manifest.market == "TPEX"
    assert loaded.manifest.contract_version == TPEX_RESEARCH_BUNDLE_CONTRACT_VERSION
    assert loaded.manifest.to_dict()["market"] == "TPEX"
    with pytest.raises(ValueError, match="requested venue"):
        _ = TwseResearchBundleReader.read(written.bundle_dir)
