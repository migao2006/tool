"""Multiclass probability calibration fitted on a separate time block."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from math import log
from typing import Any, Hashable, Iterable, Mapping, Sequence


CLASS_ORDER = ("UP", "NEUTRAL", "DOWN")
_EPSILON = 1e-12


def normalize_probabilities(values: Sequence[float]) -> tuple[float, ...]:
    clipped = [min(1.0, max(0.0, float(value))) for value in values]
    total = sum(clipped)
    if total <= 0:
        return tuple(1.0 / len(clipped) for _ in clipped)
    return tuple(value / total for value in clipped)


def _as_rows(probabilities: Iterable[Mapping[str, float] | Sequence[float]]) -> list[tuple[float, ...]]:
    rows: list[tuple[float, ...]] = []
    for row in probabilities:
        values = [row[label] for label in CLASS_ORDER] if isinstance(row, Mapping) else list(row)
        if len(values) != len(CLASS_ORDER):
            raise ValueError("each probability row must contain UP, NEUTRAL, and DOWN")
        rows.append(normalize_probabilities(values))
    return rows


def multiclass_log_loss(probabilities: Sequence[Sequence[float]], labels: Sequence[str]) -> float:
    if len(probabilities) != len(labels) or not labels:
        raise ValueError("non-empty probabilities and labels must have equal length")
    positions = {label: index for index, label in enumerate(CLASS_ORDER)}
    return -sum(log(max(_EPSILON, row[positions[label]])) for row, label in zip(probabilities, labels)) / len(labels)


def classwise_brier_score(
    probabilities: Sequence[Sequence[float]], labels: Sequence[str]
) -> dict[str, float]:
    if len(probabilities) != len(labels) or not labels:
        raise ValueError("non-empty probabilities and labels must have equal length")
    return {
        class_name: sum(
            (row[index] - float(label == class_name)) ** 2 for row, label in zip(probabilities, labels)
        )
        / len(labels)
        for index, class_name in enumerate(CLASS_ORDER)
    }


def expected_calibration_error(
    probabilities: Sequence[Sequence[float]], labels: Sequence[str], bins: int = 10
) -> float:
    if bins <= 0 or len(probabilities) != len(labels) or not labels:
        raise ValueError("valid bins and equal non-empty inputs are required")
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for row, label in zip(probabilities, labels):
        predicted_index = max(range(len(row)), key=lambda index: row[index])
        confidence = row[predicted_index]
        bucket = min(bins - 1, int(confidence * bins))
        buckets[bucket].append((confidence, CLASS_ORDER[predicted_index] == label))
    total = len(labels)
    return sum(
        len(bucket) / total
        * abs(sum(item[0] for item in bucket) / len(bucket) - sum(item[1] for item in bucket) / len(bucket))
        for bucket in buckets
        if bucket
    )


@dataclass(frozen=True)
class ProbabilityCalibrationAudit:
    method: str
    calibration_size: int
    uncalibrated_log_loss: float
    calibrated_log_loss: float


class ProbabilityCalibrator:
    """Temperature scaling or one-vs-rest sigmoid calibration.

    Calibration and base-training sample identities are mandatory so an
    integration cannot silently calibrate on model-training rows.
    """

    def __init__(self, method: str = "temperature", version: str = "probability-calibration-v1") -> None:
        if method not in {"temperature", "sigmoid"}:
            raise ValueError("method must be 'temperature' or 'sigmoid'")
        self.method = method
        self.version = version
        self.temperature: float | None = None
        self.sigmoid_models: list[Any] = []
        self.audit: ProbabilityCalibrationAudit | None = None

    def fit(
        self,
        probabilities: Iterable[Mapping[str, float] | Sequence[float]],
        labels: Sequence[str],
        calibration_ids: Sequence[Hashable] | None = None,
        base_training_ids: Iterable[Hashable] | None = None,
    ) -> "ProbabilityCalibrator":
        rows = _as_rows(probabilities)
        normalized_labels = [str(label) for label in labels]
        if len(rows) != len(normalized_labels) or not rows:
            raise ValueError("non-empty probabilities and labels must have equal length")
        if any(label not in CLASS_ORDER for label in normalized_labels):
            raise ValueError(f"labels must be one of {CLASS_ORDER}")
        if calibration_ids is None or base_training_ids is None:
            raise ValueError("calibration IDs and base-training IDs are required")
        if len(calibration_ids) != len(rows):
            raise ValueError("one calibration ID is required per row")
        overlap = set(calibration_ids).intersection(base_training_ids)
        if overlap:
            raise ValueError("base-model training and calibration samples must be disjoint")
        before = multiclass_log_loss(rows, normalized_labels)
        if self.method == "temperature":
            candidates = [0.25 + 0.05 * index for index in range(76)]
            self.temperature = min(
                candidates,
                key=lambda value: multiclass_log_loss(self._temperature_transform(rows, value), normalized_labels),
            )
        else:
            try:
                logistic_regression = import_module("sklearn.linear_model").LogisticRegression
            except ModuleNotFoundError as error:
                raise RuntimeError("scikit-learn is required for sigmoid calibration") from error
            logits = [[log(max(_EPSILON, value) / max(_EPSILON, 1 - value)) for value in row] for row in rows]
            self.sigmoid_models = []
            for index, class_name in enumerate(CLASS_ORDER):
                model = logistic_regression(max_iter=1000)
                model.fit([[row[index]] for row in logits], [int(label == class_name) for label in normalized_labels])
                self.sigmoid_models.append(model)
        transformed = self.transform_rows(rows)
        self.audit = ProbabilityCalibrationAudit(
            method=self.method,
            calibration_size=len(rows),
            uncalibrated_log_loss=before,
            calibrated_log_loss=multiclass_log_loss(transformed, normalized_labels),
        )
        return self

    @staticmethod
    def _temperature_transform(rows: Sequence[Sequence[float]], temperature: float) -> list[tuple[float, ...]]:
        return [normalize_probabilities([max(_EPSILON, value) ** (1.0 / temperature) for value in row]) for row in rows]

    def transform_rows(
        self, probabilities: Iterable[Mapping[str, float] | Sequence[float]]
    ) -> list[tuple[float, ...]]:
        rows = _as_rows(probabilities)
        if self.method == "temperature":
            if self.temperature is None:
                raise RuntimeError("probability calibrator has not been fitted")
            return self._temperature_transform(rows, self.temperature)
        if len(self.sigmoid_models) != len(CLASS_ORDER):
            raise RuntimeError("probability calibrator has not been fitted")
        output: list[tuple[float, ...]] = []
        for row in rows:
            calibrated = []
            for index, (value, model) in enumerate(zip(row, self.sigmoid_models)):
                raw_logit = log(max(_EPSILON, value) / max(_EPSILON, 1 - value))
                calibrated.append(float(model.predict_proba([[raw_logit]])[0][1]))
            output.append(normalize_probabilities(calibrated))
        return output

    def transform_named(
        self, probabilities: Iterable[Mapping[str, float] | Sequence[float]]
    ) -> list[dict[str, float]]:
        return [
            {f"calibrated_p_{label.lower()}": value for label, value in zip(CLASS_ORDER, row)}
            for row in self.transform_rows(probabilities)
        ]
