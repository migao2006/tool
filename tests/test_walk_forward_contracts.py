from __future__ import annotations

from datetime import date, timedelta
import random
from time import monotonic

import pytest

from src.validation.purged_walk_forward import (
    LabeledObservation,
    PurgedWalkForwardSplitter,
    assert_zero_label_overlap,
    locked_holdout_split,
    purge_overlaps,
)
from src.validation.ranking_metrics import ndcg_at_k, spearman_rank_ic
from src.validation.time_series_statistics import moving_block_bootstrap_mean


def observations(count: int = 16, label_days: int = 2) -> list[LabeledObservation]:
    start = date(2026, 1, 1)
    return [
        LabeledObservation(
            sample_id=f"row-{index}",
            decision_date=start + timedelta(days=index),
            entry_at=start + timedelta(days=index + 1),
            exit_at=start + timedelta(days=index + label_days),
        )
        for index in range(count)
    ]


def test_purge_uses_label_windows_and_keeps_partitions_disjoint() -> None:
    rows = observations()
    splitter = PurgedWalkForwardSplitter(4, 2, 2, purge_trading_dates=0, step_dates=2)
    fold = next(splitter.split(rows))
    assert len(fold.train_indices) < 4  # late train label overlaps calibration and is purged
    assert_zero_label_overlap(rows, fold.train_indices, fold.calibration_indices, fold.test_indices)


def test_same_decision_date_cross_section_stays_atomic() -> None:
    rows = observations()
    rows.append(
        LabeledObservation("second-stock", rows[0].decision_date, rows[0].entry_at, rows[0].exit_at)
    )
    fold = next(PurgedWalkForwardSplitter(4, 2, 2, 1).split(rows))
    partitions = [set(partition) for partition in (fold.train_indices, fold.calibration_indices, fold.test_indices)]
    owners = [number for number, partition in enumerate(partitions) if 0 in partition or len(rows) - 1 in partition]
    assert len(set(owners)) <= 1


def test_purge_removes_an_entire_cross_section_when_one_label_overlaps() -> None:
    rows = observations()
    duplicate = LabeledObservation(
        "long-label",
        rows[3].decision_date,
        rows[3].entry_at,
        rows[3].exit_at + timedelta(days=5),
    )
    rows.append(duplicate)
    fold = next(PurgedWalkForwardSplitter(4, 2, 2, purge_trading_dates=0).split(rows))
    same_date_indices = {3, len(rows) - 1}
    assert same_date_indices.isdisjoint(fold.train_indices)


def test_locked_holdout_is_purged_once() -> None:
    rows = observations(20)
    development, holdout = locked_holdout_split(rows, holdout_trading_dates=4, purge_trading_dates=2)
    assert development and holdout
    assert_zero_label_overlap(rows, development, holdout)


def _naive_purge_overlaps(
    candidate_indices: list[int],
    protected_indices: list[int],
    rows: list[LabeledObservation],
) -> tuple[int, ...]:
    blocked_dates = {
        rows[index].decision_date
        for index in candidate_indices
        if any(
            rows[index].entry_at <= rows[other].exit_at
            and rows[other].entry_at <= rows[index].exit_at
            for other in protected_indices
        )
    }
    return tuple(
        index
        for index in candidate_indices
        if rows[index].decision_date not in blocked_dates
    )


def test_interval_index_matches_naive_purge_on_random_cross_sections() -> None:
    generator = random.Random(20260719)
    start = date(2025, 1, 1)
    for _ in range(40):
        rows: list[LabeledObservation] = []
        for index in range(80):
            decision_date = start + timedelta(days=index // 4)
            entry_at = decision_date + timedelta(days=generator.randint(0, 4))
            exit_at = entry_at + timedelta(days=generator.randint(0, 6))
            rows.append(
                LabeledObservation(
                    sample_id=index,
                    decision_date=decision_date,
                    entry_at=entry_at,
                    exit_at=exit_at,
                )
            )
        shuffled = list(range(len(rows)))
        generator.shuffle(shuffled)
        split = generator.randint(0, len(shuffled))
        candidates = shuffled[:split]
        protected = shuffled[split:]
        assert purge_overlaps(candidates, protected, rows) == _naive_purge_overlaps(
            candidates,
            protected,
            rows,
        )


def test_large_cross_section_overlap_checks_remain_bounded() -> None:
    start = date(2020, 1, 1)
    rows: list[LabeledObservation] = []
    candidate_indices: list[int] = []
    protected_indices: list[int] = []
    for day_offset in range(40):
        decision_date = start + timedelta(days=day_offset)
        for symbol_offset in range(500):
            candidate_indices.append(len(rows))
            rows.append(
                LabeledObservation(
                    sample_id=f"candidate-{day_offset}-{symbol_offset}",
                    decision_date=decision_date,
                    entry_at=decision_date + timedelta(days=1),
                    exit_at=decision_date + timedelta(days=5),
                )
            )
    protected_start = start + timedelta(days=365)
    for day_offset in range(40):
        decision_date = protected_start + timedelta(days=day_offset)
        for symbol_offset in range(500):
            protected_indices.append(len(rows))
            rows.append(
                LabeledObservation(
                    sample_id=f"protected-{day_offset}-{symbol_offset}",
                    decision_date=decision_date,
                    entry_at=decision_date + timedelta(days=1),
                    exit_at=decision_date + timedelta(days=5),
                )
            )

    started_at = monotonic()
    kept = purge_overlaps(candidate_indices, protected_indices, rows)
    assert_zero_label_overlap(rows, kept, protected_indices)
    elapsed = monotonic() - started_at

    assert kept == tuple(candidate_indices)
    assert elapsed < 5.0


def test_ranking_metrics_and_block_bootstrap_are_deterministic() -> None:
    assert ndcg_at_k([3, 2, 1], [3, 2, 1], 3) == pytest.approx(1.0)
    assert spearman_rank_ic([1, 2, 3], [10, 20, 30]) == pytest.approx(1.0)
    first = moving_block_bootstrap_mean([1, 2, 3, 4, 5], block_length=2, samples=50)
    second = moving_block_bootstrap_mean([1, 2, 3, 4, 5], block_length=2, samples=50)
    assert first == second
