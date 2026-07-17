"""Cross-sectional rank model; the sole source of stock ordering."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from importlib import import_module
from math import floor
from typing import Any, Iterable, Mapping, Sequence

from ..model_contracts import validate_horizon


@dataclass(frozen=True)
class RankingConfig:
    horizon: int = 5
    relevance_levels: int = 10
    eval_at: tuple[int, ...] = (10, 20, 50)
    lambdarank_truncation_level: int = 53
    random_seed: int = 20260718

    def __post_init__(self) -> None:
        validate_horizon(self.horizon)
        if self.relevance_levels != 10:
            raise ValueError("the MVP relevance contract is fixed to integer grades 0..9")
        if not self.eval_at or min(self.eval_at) <= 0:
            raise ValueError("eval_at must contain positive Top-K values")


def make_relevance_labels(
    decision_dates: Sequence[Any], net_alphas: Sequence[float], levels: int = 10
) -> list[int]:
    """Convert each date's continuous net alpha into deterministic 0..9 grades.

    The rule is fixed before model evaluation: average within-date ordinal
    percentile followed by equal-width percentile bins. Ties receive one grade.
    """

    if levels != 10:
        raise ValueError("relevance levels must be 10")
    if len(decision_dates) != len(net_alphas):
        raise ValueError("decision_dates and net_alphas must have equal length")
    by_date: dict[Any, list[int]] = defaultdict(list)
    for index, decision_date in enumerate(decision_dates):
        by_date[decision_date].append(index)
    labels = [0] * len(net_alphas)
    for indices in by_date.values():
        ordered = sorted(indices, key=lambda i: (float(net_alphas[i]), i))
        count = len(ordered)
        if count == 1:
            labels[ordered[0]] = levels // 2
            continue
        cursor = 0
        while cursor < count:
            end = cursor + 1
            value = float(net_alphas[ordered[cursor]])
            while end < count and float(net_alphas[ordered[end]]) == value:
                end += 1
            average_rank = (cursor + end - 1) / 2
            grade = min(levels - 1, floor((average_rank / (count - 1)) * levels))
            for position in range(cursor, end):
                labels[ordered[position]] = grade
            cursor = end
    return labels


def ordered_groups(decision_dates: Sequence[Any]) -> tuple[list[int], list[int]]:
    """Return a date-contiguous row order and LightGBM query group sizes."""

    by_date: dict[Any, list[int]] = defaultdict(list)
    for index, decision_date in enumerate(decision_dates):
        by_date[decision_date].append(index)
    ordered_indices: list[int] = []
    group_sizes: list[int] = []
    for decision_date in sorted(by_date):
        indices = by_date[decision_date]
        ordered_indices.extend(indices)
        group_sizes.append(len(indices))
    return ordered_indices, group_sizes


def _take_rows(values: Any, indices: Sequence[int]) -> Any:
    if hasattr(values, "iloc"):
        return values.iloc[list(indices)]
    try:
        return values[list(indices)]
    except (TypeError, IndexError):
        return [values[index] for index in indices]


class LGBMStockRanker:
    """Lazy LightGBM LambdaMART adapter with date-level query grouping."""

    def __init__(self, config: RankingConfig | None = None, **model_params: Any) -> None:
        self.config = config or RankingConfig()
        self.model_params = model_params
        self.model: Any | None = None

    def fit(self, features: Any, relevance: Sequence[int], decision_dates: Sequence[Any]) -> "LGBMStockRanker":
        if len(relevance) != len(decision_dates):
            raise ValueError("relevance and decision_dates must have equal length")
        if any(label < 0 or label > 9 or int(label) != label for label in relevance):
            raise ValueError("LambdaRank relevance labels must be integers from 0 through 9")
        try:
            lightgbm = import_module("lightgbm")
        except ModuleNotFoundError as error:
            raise RuntimeError("LightGBM is required to train LGBMStockRanker") from error
        order, groups = ordered_groups(decision_dates)
        parameters = {
            "objective": "lambdarank",
            "metric": "ndcg",
            "eval_at": self.config.eval_at,
            "lambdarank_truncation_level": self.config.lambdarank_truncation_level,
            "random_state": self.config.random_seed,
        }
        parameters.update(self.model_params)
        self.model = lightgbm.LGBMRanker(**parameters)
        self.model.fit(_take_rows(features, order), _take_rows(relevance, order), group=groups)
        return self

    def predict(self, features: Any) -> list[float]:
        if self.model is None:
            raise RuntimeError("rank model has not been fitted")
        return [float(value) for value in self.model.predict(features)]


def rank_cross_section(
    rows: Iterable[Mapping[str, Any]], score_key: str = "model_raw_score"
) -> list[dict[str, Any]]:
    """Add global/industry ranks; no other model signal is used."""

    materialized = [dict(row) for row in rows]
    by_date: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in materialized:
        by_date[row["decision_date"]].append(row)
    output: list[dict[str, Any]] = []
    for date_rows in by_date.values():
        ordered = sorted(date_rows, key=lambda row: (-float(row[score_key]), str(row["symbol"])))
        total = len(ordered)
        for rank, row in enumerate(ordered, start=1):
            percentile = 1.0 if total == 1 else (total - rank) / (total - 1)
            row["global_rank"] = rank
            row["global_rank_percentile"] = percentile
            row["rank_score"] = 100.0 * percentile
        by_industry: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in ordered:
            by_industry[str(row.get("industry", "UNKNOWN"))].append(row)
        for industry_rows in by_industry.values():
            industry_rows.sort(key=lambda row: (-float(row[score_key]), str(row["symbol"])))
            size = len(industry_rows)
            for rank, row in enumerate(industry_rows, start=1):
                row["industry_rank"] = rank
                row["industry_rank_percentile"] = (
                    1.0 if size == 1 else (size - rank) / (size - 1)
                )
        output.extend(ordered)
    return output


def random_baseline_scores(keys: Iterable[str], seed: int = 20260718) -> list[float]:
    """Reproducible random-ranking baseline independent of Python hash state."""

    return [
        int.from_bytes(sha256(f"{seed}:{key}".encode("utf-8")).digest()[:8], "big") / 2**64
        for key in keys
    ]


def momentum_baseline_scores(rows: Iterable[Mapping[str, float]], window: int) -> list[float]:
    if window not in (5, 20):
        raise ValueError("the defined momentum baselines are 5 and 20 trading days")
    field = f"total_return_{window}d"
    return [float(row[field]) for row in rows]


class RegressThenRankBaseline:
    """Linear or LightGBM regression baseline whose predictions are only sorted."""

    def __init__(self, backend: str = "linear", random_seed: int = 20260718) -> None:
        if backend not in {"linear", "lightgbm"}:
            raise ValueError("backend must be 'linear' or 'lightgbm'")
        self.backend = backend
        self.random_seed = random_seed
        self.model: Any | None = None

    def fit(self, features: Any, net_alpha: Sequence[float]) -> "RegressThenRankBaseline":
        try:
            if self.backend == "linear":
                model_class = import_module("sklearn.linear_model").LinearRegression
                self.model = model_class()
            else:
                model_class = import_module("lightgbm").LGBMRegressor
                self.model = model_class(random_state=self.random_seed)
        except ModuleNotFoundError as error:
            raise RuntimeError(f"{self.backend} training dependency is not installed") from error
        self.model.fit(features, net_alpha)
        return self

    def predict(self, features: Any) -> list[float]:
        if self.model is None:
            raise RuntimeError("baseline has not been fitted")
        return [float(value) for value in self.model.predict(features)]
