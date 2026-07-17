"""Fold-scoped non-critical missing-value preprocessing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from statistics import median
from typing import Mapping, Sequence


@dataclass(frozen=True)
class FoldFitScope:
    fold_id: str
    train_end_at: datetime

    def __post_init__(self) -> None:
        if not self.fold_id:
            raise ValueError("fold_id is required")
        if self.train_end_at.tzinfo is None or self.train_end_at.utcoffset() is None:
            raise ValueError("train_end_at must be timezone-aware")


class CrossSectionalMedianImputer:
    """Use each day's cross-sectional median with a training-fold fallback.

    The fallback is used only when an entire inference cross-section lacks a
    non-critical feature. It is fit solely on the corresponding fold's training rows.
    """

    def __init__(self) -> None:
        self._medians: dict[str, float] | None = None
        self.fit_scope: FoldFitScope | None = None

    def fit(
        self,
        rows: Sequence[Mapping[str, float | int | None]],
        *,
        feature_names: Sequence[str],
        scope: FoldFitScope,
        row_available_ats: Sequence[datetime],
    ) -> "CrossSectionalMedianImputer":
        if len(rows) != len(row_available_ats):
            raise ValueError("rows and row_available_ats must have equal length")
        if any(available_at > scope.train_end_at for available_at in row_available_ats):
            raise ValueError("preprocessor fit data extends beyond the fold training end")
        medians: dict[str, float] = {}
        for name in feature_names:
            values = [float(row[name]) for row in rows if row.get(name) is not None]
            if not values:
                raise ValueError(f"cannot fit median for entirely missing feature: {name}")
            medians[name] = median(values)
        self._medians = medians
        self.fit_scope = scope
        return self

    def transform(
        self,
        rows: Sequence[Mapping[str, float | int | None]],
        *,
        decision_dates: Sequence[date],
    ) -> list[dict[str, float]]:
        if self._medians is None:
            raise RuntimeError("imputer must be fit inside a training fold before transform")
        if len(rows) != len(decision_dates):
            raise ValueError("rows and decision_dates must have equal length")
        cross_section_medians: dict[tuple[date, str], float] = {}
        for current_date in set(decision_dates):
            indices = [index for index, row_date in enumerate(decision_dates) if row_date == current_date]
            for name, fallback in self._medians.items():
                values = [float(rows[index][name]) for index in indices if rows[index].get(name) is not None]
                cross_section_medians[(current_date, name)] = median(values) if values else fallback
        transformed: list[dict[str, float]] = []
        for row, current_date in zip(rows, decision_dates):
            output: dict[str, float] = {}
            for name in self._medians:
                missing = row.get(name) is None
                output[name] = (
                    cross_section_medians[(current_date, name)]
                    if missing
                    else float(row[name])
                )
                output[f"{name}__missing"] = float(missing)
            transformed.append(output)
        return transformed
