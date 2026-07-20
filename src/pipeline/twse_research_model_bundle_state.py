"""Explicit JSON codecs for preprocessing and calibration bundle state."""

# pyright: reportAny=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from datetime import datetime
import json
from math import isfinite
from pathlib import Path
from typing import cast

import numpy as np

from src.calibration.interval_calibrator import (
    IntervalCalibrationAudit,
    IntervalCalibrator,
)
from src.calibration.probability_calibrator import (
    ProbabilityCalibrationAudit,
    ProbabilityCalibrator,
)
from src.data.preprocessing import CrossSectionalMedianImputer, FoldFitScope

from .twse_research_model_bundle_contracts import (
    TwseResearchModelBundleManifest,
)


IMPUTER_STATE_VERSION = "cross-sectional-median-imputer-v1"
PROBABILITY_STATE_VERSION = "temperature-calibrator-v1"
INTERVAL_STATE_VERSION = "additive-interval-calibrator-v1"


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def imputer_payload(
    imputer: CrossSectionalMedianImputer, feature_names: Sequence[str]
) -> bytes:
    if imputer.fit_scope is None:
        raise ValueError("bundle imputer has not been fitted")
    names = tuple(feature_names)
    fallback_matrix = imputer.transform_array(
        np.full((1, len(names)), np.nan, dtype=np.float64),
        decision_dates=(imputer.fit_scope.train_end_at.date(),),
        output_dtype=np.float64,
    )
    medians = {
        name: float(fallback_matrix[0, index * 2]) for index, name in enumerate(names)
    }
    return _canonical_json(
        {
            "state_version": IMPUTER_STATE_VERSION,
            "feature_names": list(names),
            "training_medians": medians,
            "fit_scope": {
                "fold_id": imputer.fit_scope.fold_id,
                "train_end_at": imputer.fit_scope.train_end_at.isoformat(),
            },
        }
    )


def probability_payload(calibrator: ProbabilityCalibrator) -> bytes:
    if calibrator.method != "temperature" or calibrator.temperature is None:
        raise ValueError("only explicit temperature calibration can be persisted")
    if calibrator.audit is None:
        raise ValueError("probability calibrator audit is required")
    return _canonical_json(
        {
            "state_version": PROBABILITY_STATE_VERSION,
            "method": calibrator.method,
            "version": calibrator.version,
            "temperature": calibrator.temperature,
            "audit": {
                "method": calibrator.audit.method,
                "calibration_size": calibrator.audit.calibration_size,
                "uncalibrated_log_loss": calibrator.audit.uncalibrated_log_loss,
                "calibrated_log_loss": calibrator.audit.calibrated_log_loss,
            },
        }
    )


def interval_payload(calibrator: IntervalCalibrator) -> bytes:
    if calibrator.offsets is None or calibrator.audit is None:
        raise ValueError("fitted interval calibrator state and audit are required")
    return _canonical_json(
        {
            "state_version": INTERVAL_STATE_VERSION,
            "version": calibrator.version,
            "offsets": list(calibrator.offsets),
            "audit": {
                "raw_crossing_rate": calibrator.audit.raw_crossing_rate,
                "calibrated_crossing_rate": calibrator.audit.calibrated_crossing_rate,
                "calibration_size": calibrator.audit.calibration_size,
            },
        }
    )


def _state(path: Path, expected_version: str) -> Mapping[str, object]:
    value = cast(object, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(value, Mapping) or value.get("state_version") != expected_version:
        raise ValueError(f"unsupported explicit state: {path.name}")
    return cast(Mapping[str, object], value)


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def read_imputer(
    path: Path, manifest: TwseResearchModelBundleManifest
) -> CrossSectionalMedianImputer:
    state = _state(path, IMPUTER_STATE_VERSION)
    names = state.get("feature_names")
    medians = state.get("training_medians")
    scope = state.get("fit_scope")
    if (
        not isinstance(names, list)
        or not isinstance(medians, Mapping)
        or not isinstance(scope, Mapping)
    ):
        raise ValueError("invalid explicit imputer state")
    typed_names = cast(list[object], names)
    typed_medians = cast(Mapping[str, object], medians)
    typed_scope = cast(Mapping[str, object], scope)
    if tuple(str(value) for value in typed_names) != manifest.feature_names:
        raise ValueError("imputer feature order does not match bundle manifest")
    fit_scope = FoldFitScope(
        fold_id=str(typed_scope.get("fold_id", "")),
        train_end_at=datetime.fromisoformat(str(typed_scope.get("train_end_at", ""))),
    )
    restored_medians = {
        name: _number(typed_medians.get(name), f"training_medians.{name}")
        for name in manifest.feature_names
    }
    if set(typed_medians) != set(manifest.feature_names):
        raise ValueError("imputer medians do not match bundle feature names")
    restored = CrossSectionalMedianImputer().fit_array(
        np.asarray(
            [[restored_medians[name] for name in manifest.feature_names]],
            dtype=np.float64,
        ),
        feature_names=manifest.feature_names,
        scope=fit_scope,
        row_available_ats=(fit_scope.train_end_at,),
    )
    if (
        fit_scope.fold_id
        != f"{manifest.market.lower()}-research-fold-{manifest.fold_number}"
        or fit_scope.train_end_at.date() != manifest.training_end_date
    ):
        raise ValueError("imputer fit scope does not match bundle fold provenance")
    return restored


def read_probability(path: Path) -> ProbabilityCalibrator:
    state = _state(path, PROBABILITY_STATE_VERSION)
    audit = state.get("audit")
    if state.get("method") != "temperature" or not isinstance(audit, Mapping):
        raise ValueError("only explicit temperature calibration is supported")
    typed_audit = cast(Mapping[str, object], audit)
    calibrator = ProbabilityCalibrator(
        method="temperature", version=str(state.get("version", ""))
    )
    calibrator.temperature = _number(state.get("temperature"), "temperature")
    calibrator.audit = ProbabilityCalibrationAudit(
        method=str(typed_audit.get("method", "")),
        calibration_size=_integer(
            typed_audit.get("calibration_size"), "calibration_size"
        ),
        uncalibrated_log_loss=_number(
            typed_audit.get("uncalibrated_log_loss"), "uncalibrated_log_loss"
        ),
        calibrated_log_loss=_number(
            typed_audit.get("calibrated_log_loss"), "calibrated_log_loss"
        ),
    )
    if (
        calibrator.temperature <= 0
        or not isfinite(calibrator.temperature)
        or calibrator.audit.calibration_size <= 0
        or not isfinite(calibrator.audit.uncalibrated_log_loss)
        or not isfinite(calibrator.audit.calibrated_log_loss)
    ):
        raise ValueError("probability calibration state is invalid")
    return calibrator


def read_interval(path: Path) -> IntervalCalibrator:
    state = _state(path, INTERVAL_STATE_VERSION)
    offsets = state.get("offsets")
    audit = state.get("audit")
    if (
        not isinstance(offsets, list)
        or len(offsets) != 3
        or not isinstance(audit, Mapping)
    ):
        raise ValueError("invalid explicit interval calibration state")
    typed_offsets = cast(list[object], offsets)
    typed_audit = cast(Mapping[str, object], audit)
    restored_offsets = (
        _number(typed_offsets[0], "offsets[0]"),
        _number(typed_offsets[1], "offsets[1]"),
        _number(typed_offsets[2], "offsets[2]"),
    )
    calibrator = IntervalCalibrator(version=str(state.get("version", "")))
    calibrator.offsets = restored_offsets
    calibrator.audit = IntervalCalibrationAudit(
        raw_crossing_rate=_number(
            typed_audit.get("raw_crossing_rate"), "raw_crossing_rate"
        ),
        calibrated_crossing_rate=_number(
            typed_audit.get("calibrated_crossing_rate"),
            "calibrated_crossing_rate",
        ),
        calibration_size=_integer(
            typed_audit.get("calibration_size"), "calibration_size"
        ),
    )
    if (
        any(not isfinite(value) for value in restored_offsets)
        or calibrator.audit.calibration_size <= 0
        or not 0 <= calibrator.audit.raw_crossing_rate <= 1
        or not 0 <= calibrator.audit.calibrated_crossing_rate <= 1
    ):
        raise ValueError("interval calibration state is invalid")
    return calibrator


__all__ = [
    "imputer_payload",
    "interval_payload",
    "probability_payload",
    "read_imputer",
    "read_interval",
    "read_probability",
]
