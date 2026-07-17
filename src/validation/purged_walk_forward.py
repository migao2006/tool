"""Expanding walk-forward splits purged by entry-to-exit label windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Hashable, Iterable, Iterator, Sequence


Timestamp = date | datetime


@dataclass(frozen=True)
class LabeledObservation:
    sample_id: Hashable
    decision_date: date
    entry_at: Timestamp
    exit_at: Timestamp

    def __post_init__(self) -> None:
        if self.exit_at < self.entry_at:
            raise ValueError("label exit_at cannot precede entry_at")


@dataclass(frozen=True)
class PurgedFold:
    fold_number: int
    train_indices: tuple[int, ...]
    calibration_indices: tuple[int, ...]
    test_indices: tuple[int, ...]
    train_dates: tuple[date, date]
    calibration_dates: tuple[date, date]
    test_dates: tuple[date, date]


def label_windows_overlap(left: LabeledObservation, right: LabeledObservation) -> bool:
    return left.entry_at <= right.exit_at and right.entry_at <= left.exit_at


def purge_overlaps(
    candidate_indices: Iterable[int], protected_indices: Iterable[int], records: Sequence[LabeledObservation]
) -> tuple[int, ...]:
    candidates = tuple(candidate_indices)
    protected = tuple(protected_indices)
    blocked_dates = {
        records[index].decision_date
        for index in candidates
        if any(label_windows_overlap(records[index], records[other]) for other in protected)
    }
    return tuple(
        index
        for index in candidates
        if records[index].decision_date not in blocked_dates
    )


def assert_zero_label_overlap(
    records: Sequence[LabeledObservation], *partitions: Sequence[int]
) -> None:
    for left_position, left in enumerate(partitions):
        for right in partitions[left_position + 1 :]:
            for left_index in left:
                for right_index in right:
                    if label_windows_overlap(records[left_index], records[right_index]):
                        raise ValueError(
                            f"label windows overlap across partitions: "
                            f"{records[left_index].sample_id!r}, {records[right_index].sample_id!r}"
                        )


def assert_decision_dates_are_atomic(
    records: Sequence[LabeledObservation], *partitions: Sequence[int]
) -> None:
    owners: dict[date, int] = {}
    for partition_number, partition in enumerate(partitions):
        for index in partition:
            decision_date = records[index].decision_date
            previous = owners.setdefault(decision_date, partition_number)
            if previous != partition_number:
                raise ValueError(f"decision_date {decision_date} was split across folds")


class PurgedWalkForwardSplitter:
    """Generate expanding folds over observed trading dates.

    ``purge_trading_dates`` creates the configured embargo, while the final
    partition cleanup uses actual label windows and therefore remains valid
    for holidays, suspensions, and horizons with irregular exits.
    """

    def __init__(
        self,
        minimum_train_dates: int,
        calibration_dates: int,
        test_dates: int,
        purge_trading_dates: int = 10,
        step_dates: int | None = None,
    ) -> None:
        values = (minimum_train_dates, calibration_dates, test_dates)
        if min(values) <= 0 or purge_trading_dates < 0:
            raise ValueError("split lengths must be positive and purge non-negative")
        self.minimum_train_dates = minimum_train_dates
        self.calibration_dates = calibration_dates
        self.test_dates = test_dates
        self.purge_trading_dates = purge_trading_dates
        self.step_dates = step_dates or test_dates
        if self.step_dates <= 0:
            raise ValueError("step_dates must be positive")

    def split(self, records: Sequence[LabeledObservation]) -> Iterator[PurgedFold]:
        dates = sorted({record.decision_date for record in records})
        train_end = self.minimum_train_dates
        fold_number = 0
        while True:
            calibration_start = train_end + self.purge_trading_dates
            calibration_end = calibration_start + self.calibration_dates
            test_start = calibration_end + self.purge_trading_dates
            test_end = test_start + self.test_dates
            if test_end > len(dates):
                break
            train_date_set = set(dates[:train_end])
            calibration_date_set = set(dates[calibration_start:calibration_end])
            test_date_set = set(dates[test_start:test_end])
            train = tuple(index for index, row in enumerate(records) if row.decision_date in train_date_set)
            calibration = tuple(index for index, row in enumerate(records) if row.decision_date in calibration_date_set)
            test = tuple(index for index, row in enumerate(records) if row.decision_date in test_date_set)

            calibration = purge_overlaps(calibration, test, records)
            train = purge_overlaps(train, (*calibration, *test), records)
            assert_zero_label_overlap(records, train, calibration, test)
            assert_decision_dates_are_atomic(records, train, calibration, test)
            yield PurgedFold(
                fold_number=fold_number,
                train_indices=train,
                calibration_indices=calibration,
                test_indices=test,
                train_dates=(dates[0], dates[train_end - 1]),
                calibration_dates=(dates[calibration_start], dates[calibration_end - 1]),
                test_dates=(dates[test_start], dates[test_end - 1]),
            )
            fold_number += 1
            train_end += self.step_dates


def locked_holdout_split(
    records: Sequence[LabeledObservation], holdout_trading_dates: int, purge_trading_dates: int = 10
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Create one auditable development/locked-holdout boundary."""

    dates = sorted({record.decision_date for record in records})
    if holdout_trading_dates <= 0 or holdout_trading_dates + purge_trading_dates >= len(dates):
        raise ValueError("insufficient dates for the requested locked holdout")
    holdout_dates = set(dates[-holdout_trading_dates:])
    development_dates = set(dates[: -(holdout_trading_dates + purge_trading_dates)])
    holdout = tuple(index for index, row in enumerate(records) if row.decision_date in holdout_dates)
    development = tuple(index for index, row in enumerate(records) if row.decision_date in development_dates)
    development = purge_overlaps(development, holdout, records)
    assert_zero_label_overlap(records, development, holdout)
    assert_decision_dates_are_atomic(records, development, holdout)
    return development, holdout
