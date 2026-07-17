from __future__ import annotations

from src.models.stock.rank_model import (
    _take_rows,
    make_relevance_labels,
    ordered_groups,
    random_baseline_scores,
    rank_cross_section,
)


def test_relevance_is_binned_within_each_decision_date() -> None:
    labels = make_relevance_labels(
        ["2026-01-02"] * 3 + ["2026-01-05"] * 2,
        [-0.02, 0.0, 0.03, 0.10, -0.10],
    )
    assert labels[:3] == [0, 5, 9]
    assert labels[3:] == [9, 0]


def test_relevance_ties_receive_the_same_grade() -> None:
    labels = make_relevance_labels(["d"] * 4, [0.0, 0.1, 0.1, 0.2])
    assert labels[1] == labels[2]


def test_query_group_is_date_not_symbol() -> None:
    order, groups = ordered_groups(["2026-01-03", "2026-01-02", "2026-01-03"])
    assert order == [1, 0, 2]
    assert groups == [1, 2]


def test_rank_score_is_cross_sectional_percentile_only() -> None:
    ranked = rank_cross_section(
        [
            {"decision_date": "d", "symbol": "A", "industry": "X", "model_raw_score": 0.9},
            {"decision_date": "d", "symbol": "B", "industry": "X", "model_raw_score": 0.1},
            {"decision_date": "d", "symbol": "C", "industry": "Y", "model_raw_score": 0.5},
        ]
    )
    assert [row["symbol"] for row in ranked] == ["A", "C", "B"]
    assert [row["global_rank_percentile"] for row in ranked] == [1.0, 0.5, 0.0]
    assert [row["rank_score"] for row in ranked] == [100.0, 50.0, 0.0]
    assert ranked[0]["industry_rank"] == 1
    assert ranked[2]["industry_rank"] == 2
    assert ranked[0]["industry_rank_percentile"] == 1.0


def test_random_baseline_is_reproducible() -> None:
    assert random_baseline_scores(["d:A", "d:B"]) == random_baseline_scores(["d:A", "d:B"])


def test_ranker_row_reordering_uses_dataframe_rows_not_columns() -> None:
    import pandas as pd

    frame = pd.DataFrame({"momentum": [0.1, 0.2], "volume": [10, 20]})
    reordered = _take_rows(frame, [1, 0])
    assert reordered["momentum"].tolist() == [0.2, 0.1]
