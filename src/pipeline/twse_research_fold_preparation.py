"""Fold-local preprocessing for the TWSE research pipeline."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from src.data.preprocessing import CrossSectionalMedianImputer, FoldFitScope

from .research_dataset import PreparedResearchDataset


@dataclass(frozen=True)
class FoldMatrices:
    """Train, calibration, and test matrices prepared inside one fold."""

    train: Any
    calibration: Any
    test: Any


def frame_rows(
    frame: Any,
    indices: Sequence[int],
    names: Sequence[str],
) -> list[dict[str, float | None]]:
    """Return records for small compatibility callers.

    Large fold preparation deliberately bypasses this record-oriented helper.
    """

    positions = np.asarray(indices, dtype=np.intp)
    columns = frame.columns.get_indexer(list(names))
    if np.any(columns < 0):
        raise ValueError("one or more requested frame columns are missing")
    return frame.iloc[positions, columns].to_dict(orient="records")


def frame_dates(frame: Any, indices: Sequence[int]) -> list[date]:
    positions = np.asarray(indices, dtype=np.intp)
    column = frame.columns.get_loc("decision_date")
    return frame.iloc[positions, column].tolist()


def _frame_features(
    frame: Any,
    indices: Sequence[int] | np.ndarray[Any, Any],
    names: Sequence[str],
) -> Any:
    positions = np.asarray(indices, dtype=np.intp)
    columns = frame.columns.get_indexer(list(names))
    if np.any(columns < 0):
        raise ValueError("one or more research feature columns are missing")
    return frame.iloc[positions, columns]


def _frame_column(
    frame: Any,
    indices: Sequence[int] | np.ndarray[Any, Any],
    name: str,
) -> Any:
    positions = np.asarray(indices, dtype=np.intp)
    return frame.iloc[positions, frame.columns.get_loc(name)]


def prepare_fold(
    dataset: PreparedResearchDataset,
    *,
    train_indices: Sequence[int],
    calibration_indices: Sequence[int],
    test_indices: Sequence[int],
    fold_number: int,
) -> FoldMatrices:
    """Fit preprocessing only on training rows and transform all fold slices."""

    frame = dataset.frame
    train_positions = np.asarray(train_indices, dtype=np.intp)
    calibration_positions = np.asarray(calibration_indices, dtype=np.intp)
    test_positions = np.asarray(test_indices, dtype=np.intp)
    train_features = _frame_features(
        frame,
        train_positions,
        dataset.feature_names,
    )
    train_decision_ats = _frame_column(frame, train_positions, "decision_at")
    train_available_ats = _frame_column(frame, train_positions, "available_at")
    imputer = CrossSectionalMedianImputer().fit_frame(
        train_features,
        feature_names=dataset.feature_names,
        scope=FoldFitScope(
            fold_id=f"twse-research-fold-{fold_number}",
            train_end_at=train_decision_ats.max().to_pydatetime(),
        ),
        row_available_ats=train_available_ats,
    )

    def transform(
        positions: np.ndarray[Any, Any],
        features: Any | None = None,
    ) -> Any:
        feature_frame = (
            features
            if features is not None
            else _frame_features(frame, positions, dataset.feature_names)
        )
        return imputer.transform_frame(
            feature_frame,
            decision_dates=_frame_column(
                frame,
                positions,
                "decision_date",
            ).to_numpy(copy=False),
            output_dtype=np.float32,
        )

    return FoldMatrices(
        train=transform(train_positions, train_features),
        calibration=transform(calibration_positions),
        test=transform(test_positions),
    )
