"""Fold-local preprocessing for the TWSE research pipeline."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

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
    return frame.iloc[list(indices)][list(names)].to_dict(orient="records")


def frame_dates(frame: Any, indices: Sequence[int]) -> list[date]:
    return [value for value in frame.iloc[list(indices)]["decision_date"]]


def prepare_fold(
    dataset: PreparedResearchDataset,
    *,
    train_indices: Sequence[int],
    calibration_indices: Sequence[int],
    test_indices: Sequence[int],
    fold_number: int,
) -> FoldMatrices:
    """Fit preprocessing only on training rows and transform all fold slices."""

    import pandas as pd

    frame = dataset.frame
    imputer = CrossSectionalMedianImputer().fit(
        frame_rows(frame, train_indices, dataset.feature_names),
        feature_names=dataset.feature_names,
        scope=FoldFitScope(
            fold_id=f"twse-research-fold-{fold_number}",
            train_end_at=max(
                value.to_pydatetime()
                for value in frame.iloc[list(train_indices)]["decision_at"]
            ),
        ),
        row_available_ats=[
            value.to_pydatetime()
            for value in frame.iloc[list(train_indices)]["available_at"]
        ],
    )

    def transform(indices: Sequence[int]) -> Any:
        values = imputer.transform(
            frame_rows(frame, indices, dataset.feature_names),
            decision_dates=frame_dates(frame, indices),
        )
        return pd.DataFrame(values)

    return FoldMatrices(
        train=transform(train_indices),
        calibration=transform(calibration_indices),
        test=transform(test_indices),
    )
