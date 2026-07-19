"""Fold-scoped non-critical missing-value preprocessing."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportArgumentType=false

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, cast

import numpy as np
import pandas as pd


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
        self._feature_names: tuple[str, ...] | None = None
        self.fit_scope: FoldFitScope | None = None

    @staticmethod
    def _feature_order(feature_names: Sequence[str]) -> tuple[str, ...]:
        names = tuple(dict.fromkeys(str(name) for name in feature_names))
        if not names or any(not name for name in names):
            raise ValueError("at least one named feature is required")
        return names

    @staticmethod
    def _numeric_matrix(values: Any, *, feature_count: int) -> np.ndarray[Any, Any]:
        matrix = np.asarray(values, dtype=np.float64)
        if matrix.ndim != 2 or matrix.shape[1] != feature_count:
            raise ValueError(
                "feature values must be a two-dimensional matrix with one column per feature"
            )
        return matrix

    @staticmethod
    def _validate_fit_availability(
        row_available_ats: Sequence[datetime],
        *,
        row_count: int,
        scope: FoldFitScope,
    ) -> None:
        if len(row_available_ats) != row_count:
            raise ValueError("rows and row_available_ats must have equal length")
        if row_count == 0:
            raise ValueError("cannot fit median on an empty training fold")
        vectorized_max = getattr(row_available_ats, "max", None)
        latest = cast(
            datetime,
            vectorized_max() if callable(vectorized_max) else max(row_available_ats),
        )
        if latest > scope.train_end_at:
            raise ValueError(
                "preprocessor fit data extends beyond the fold training end"
            )

    def fit_array(
        self,
        values: Any,
        *,
        feature_names: Sequence[str],
        scope: FoldFitScope,
        row_available_ats: Sequence[datetime],
    ) -> "CrossSectionalMedianImputer":
        """Fit fold-only fallbacks from a dense numeric matrix.

        This is the allocation-bounded path used by large research folds.  It
        stores only one scalar fallback per feature and never materializes one
        Python mapping per row.
        """

        names = self._feature_order(feature_names)
        matrix = self._numeric_matrix(values, feature_count=len(names))
        self._validate_fit_availability(
            row_available_ats,
            row_count=matrix.shape[0],
            scope=scope,
        )
        available_counts = np.count_nonzero(~np.isnan(matrix), axis=0)
        if np.any(available_counts == 0):
            missing_name = names[int(np.flatnonzero(available_counts == 0)[0])]
            raise ValueError(
                f"cannot fit median for entirely missing feature: {missing_name}"
            )
        medians = np.nanmedian(matrix, axis=0)
        self._medians = {
            name: float(medians[index]) for index, name in enumerate(names)
        }
        self._feature_names = names
        self.fit_scope = scope
        return self

    def fit_frame(
        self,
        frame: Any,
        *,
        feature_names: Sequence[str],
        scope: FoldFitScope,
        row_available_ats: Sequence[datetime],
    ) -> "CrossSectionalMedianImputer":
        """Fit directly from a pandas feature frame without record dictionaries."""

        names = self._feature_order(feature_names)
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("frame must be a pandas DataFrame")
        missing = [name for name in names if name not in frame.columns]
        if missing:
            raise ValueError("feature columns are missing: " + ", ".join(missing))
        values = frame.loc[:, list(names)].to_numpy(
            dtype=np.float64,
            na_value=np.nan,
            copy=False,
        )
        return self.fit_array(
            values,
            feature_names=names,
            scope=scope,
            row_available_ats=row_available_ats,
        )

    def fit(
        self,
        rows: Sequence[Mapping[str, float | int | None]],
        *,
        feature_names: Sequence[str],
        scope: FoldFitScope,
        row_available_ats: Sequence[datetime],
    ) -> "CrossSectionalMedianImputer":
        names = self._feature_order(feature_names)
        values = [[row.get(name) for name in names] for row in rows]
        return self.fit_array(
            values,
            feature_names=names,
            scope=scope,
            row_available_ats=row_available_ats,
        )

    def transform_array(
        self,
        values: Any,
        *,
        decision_dates: Sequence[date],
        output_dtype: Any = np.float32,
    ) -> np.ndarray[Any, Any]:
        """Impute a matrix in O(rows × features) with bounded intermediates.

        Exact medians are calculated independently for each decision-date
        cross-section.  A feature that is absent from an entire cross-section
        falls back to the value fit on this fold's training rows only.
        """

        if self._medians is None or self._feature_names is None:
            raise RuntimeError(
                "imputer must be fit inside a training fold before transform"
            )
        matrix = self._numeric_matrix(
            values,
            feature_count=len(self._feature_names),
        )
        if matrix.shape[0] != len(decision_dates):
            raise ValueError("rows and decision_dates must have equal length")

        dtype = np.dtype(output_dtype)
        if not np.issubdtype(dtype, np.floating):
            raise ValueError("output_dtype must be a floating-point dtype")
        row_count, feature_count = matrix.shape
        output = np.empty((row_count, feature_count * 2), dtype=dtype)
        features = output[:, 0::2]
        features[:] = matrix
        missing = np.isnan(features)
        output[:, 1::2] = missing
        if row_count == 0:
            return output

        codes, unique_dates = pd.factorize(
            np.asarray(decision_dates, dtype=object),
            sort=False,
        )
        if len(unique_dates) == 0 or np.any(codes < 0):
            raise ValueError("decision_dates cannot contain missing values")
        if not missing.any():
            return output
        group_medians = (
            pd.DataFrame(features, copy=False)
            .groupby(codes, sort=False, observed=True)
            .median()
            .reindex(range(len(unique_dates)))
            .to_numpy(dtype=dtype, copy=False)
        )
        fallbacks = np.asarray(
            [self._medians[name] for name in self._feature_names],
            dtype=dtype,
        )
        group_medians = np.where(np.isnan(group_medians), fallbacks, group_medians)
        for feature_index in range(feature_count):
            feature_missing = missing[:, feature_index]
            if feature_missing.any():
                features[feature_missing, feature_index] = group_medians[
                    codes[feature_missing], feature_index
                ]
        return output

    def transform_frame(
        self,
        frame: Any,
        *,
        decision_dates: Sequence[date],
        output_dtype: Any = np.float32,
    ) -> Any:
        """Transform a pandas frame through the allocation-bounded array path."""

        if self._feature_names is None:
            raise RuntimeError(
                "imputer must be fit inside a training fold before transform"
            )
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("frame must be a pandas DataFrame")
        missing = [name for name in self._feature_names if name not in frame.columns]
        if missing:
            raise ValueError("feature columns are missing: " + ", ".join(missing))
        values = frame.loc[:, list(self._feature_names)].to_numpy(
            dtype=np.float64,
            na_value=np.nan,
            copy=False,
        )
        transformed = self.transform_array(
            values,
            decision_dates=decision_dates,
            output_dtype=output_dtype,
        )
        columns = [
            column
            for name in self._feature_names
            for column in (name, f"{name}__missing")
        ]
        return pd.DataFrame(transformed, columns=pd.Index(columns))

    def transform(
        self,
        rows: Sequence[Mapping[str, float | int | None]],
        *,
        decision_dates: Sequence[date],
    ) -> list[dict[str, float]]:
        if self._feature_names is None:
            raise RuntimeError(
                "imputer must be fit inside a training fold before transform"
            )
        values = [[row.get(name) for name in self._feature_names] for row in rows]
        transformed = self.transform_array(
            values,
            decision_dates=decision_dates,
            output_dtype=np.float64,
        )
        columns = [
            column
            for name in self._feature_names
            for column in (name, f"{name}__missing")
        ]
        return [
            {name: float(value) for name, value in zip(columns, row)}
            for row in transformed
        ]
