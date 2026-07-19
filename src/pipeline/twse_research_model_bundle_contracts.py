"""Versioned contracts for a native-LightGBM TWSE research bundle."""

# pyright: reportUnknownArgumentType=false, reportUnknownVariableType=false

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json

from src.core.horizon import require_production_horizon


TWSE_RESEARCH_BUNDLE_CONTRACT_VERSION = "twse-research-model-bundle-v1"
MECHANICAL_LAST_FOLD_POLICY = "MECHANICAL_LAST_WALK_FORWARD_FOLD"
BUNDLE_FILE_NAMES = {
    "rank_booster": "rank.txt",
    "direction_booster": "direction.txt",
    "q10_booster": "q10.txt",
    "q50_booster": "q50.txt",
    "q90_booster": "q90.txt",
    "imputer_state": "imputer.json",
    "probability_calibrator_state": "probability-calibrator.json",
    "interval_calibrator_state": "interval-calibrator.json",
}


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _non_empty(value: object, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{field_name} must be an integer")
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be an integer") from error


@dataclass(frozen=True)
class BundleFileRecord:
    relative_path: str
    sha256: str
    byte_size: int

    def __post_init__(self) -> None:
        if not self.relative_path or self.relative_path.startswith(("/", "\\")):
            raise ValueError("bundle file path must be relative")
        if ".." in self.relative_path.replace("\\", "/").split("/"):
            raise ValueError("bundle file path cannot escape the bundle")
        _require_sha256(self.sha256, "bundle file sha256")
        if self.byte_size <= 0:
            raise ValueError("bundle file byte_size must be positive")

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "BundleFileRecord":
        return cls(
            relative_path=_non_empty(value.get("relative_path"), "relative_path"),
            sha256=_non_empty(value.get("sha256"), "sha256"),
            byte_size=_integer(value.get("byte_size", 0), "byte_size"),
        )


@dataclass(frozen=True)
class TwseResearchModelBundleManifest:
    model_version: str
    horizon: int
    fold_number: int
    feature_schema_hash: str
    input_artifact_sha256: str
    source_hash: str
    dataset_snapshot_id: str
    label_version: str
    benchmark_id: str
    benchmark_version: str
    cost_profile_version: str
    random_seed: int
    feature_names: tuple[str, ...]
    direction_classes: tuple[str, ...]
    training_start_date: date
    training_end_date: date
    calibration_start_date: date
    calibration_end_date: date
    evaluated_test_start_date: date
    evaluated_test_end_date: date
    created_at: datetime
    files: Mapping[str, BundleFileRecord]
    library_versions: Mapping[str, str]
    reason_codes: tuple[str, ...]
    git_commit: str | None = None
    contract_version: str = TWSE_RESEARCH_BUNDLE_CONTRACT_VERSION
    system_status: str = "RESEARCH_ONLY"
    selection_policy: str = MECHANICAL_LAST_FOLD_POLICY
    locked_holdout_executed: bool = False

    def __post_init__(self) -> None:
        _ = require_production_horizon(self.horizon)
        if self.contract_version != TWSE_RESEARCH_BUNDLE_CONTRACT_VERSION:
            raise ValueError("unsupported model bundle contract version")
        if self.system_status != "RESEARCH_ONLY":
            raise ValueError("this bundle cannot be promoted beyond RESEARCH_ONLY")
        if self.selection_policy != MECHANICAL_LAST_FOLD_POLICY:
            raise ValueError("bundle selection must use the mechanical last fold")
        if self.locked_holdout_executed:
            raise ValueError("research bundle must not execute the locked holdout")
        if self.fold_number < 0:
            raise ValueError("fold_number cannot be negative")
        required_text = {
            "model_version": self.model_version,
            "dataset_snapshot_id": self.dataset_snapshot_id,
            "label_version": self.label_version,
            "benchmark_id": self.benchmark_id,
            "benchmark_version": self.benchmark_version,
            "cost_profile_version": self.cost_profile_version,
        }
        for field_name, field_value in required_text.items():
            _ = _non_empty(field_value, field_name)
        _require_sha256(self.feature_schema_hash, "feature_schema_hash")
        _require_sha256(self.input_artifact_sha256, "input_artifact_sha256")
        _require_sha256(self.source_hash, "source_hash")
        if not self.feature_names or len(set(self.feature_names)) != len(self.feature_names):
            raise ValueError("feature_names must be non-empty and unique")
        if self.direction_classes != ("DOWN", "NEUTRAL", "UP"):
            raise ValueError("direction_classes must preserve the fitted LightGBM order")
        if not (
            self.training_start_date <= self.training_end_date
            < self.calibration_start_date <= self.calibration_end_date
            < self.evaluated_test_start_date <= self.evaluated_test_end_date
        ):
            raise ValueError("bundle fold dates must preserve train/calibration/test order")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        if set(self.files) != set(BUNDLE_FILE_NAMES):
            raise ValueError("bundle manifest must enumerate every native artifact")
        if any(
            self.files[name].relative_path != relative_path
            for name, relative_path in BUNDLE_FILE_NAMES.items()
        ):
            raise ValueError("bundle artifact filenames are fixed by the contract")
        if not self.reason_codes or any(not value for value in self.reason_codes):
            raise ValueError("research bundle requires explicit reason_codes")

    def _identity_content(self) -> dict[str, object]:
        """Return only fields that determine the fitted bundle's identity.

        ``created_at`` records when a particular copy was written.  It is useful
        audit metadata, but it must not make a mechanically identical rerun look
        like a different fitted model.
        """
        return {
            "contract_version": self.contract_version,
            "system_status": self.system_status,
            "selection_policy": self.selection_policy,
            "locked_holdout_executed": self.locked_holdout_executed,
            "model_version": self.model_version,
            "horizon": self.horizon,
            "fold_number": self.fold_number,
            "feature_schema_hash": self.feature_schema_hash,
            "input_artifact_sha256": self.input_artifact_sha256,
            "source_hash": self.source_hash,
            "dataset_snapshot_id": self.dataset_snapshot_id,
            "label_version": self.label_version,
            "benchmark_id": self.benchmark_id,
            "benchmark_version": self.benchmark_version,
            "cost_profile_version": self.cost_profile_version,
            "random_seed": self.random_seed,
            "feature_names": list(self.feature_names),
            "direction_classes": list(self.direction_classes),
            "training_start_date": self.training_start_date.isoformat(),
            "training_end_date": self.training_end_date.isoformat(),
            "calibration_start_date": self.calibration_start_date.isoformat(),
            "calibration_end_date": self.calibration_end_date.isoformat(),
            "evaluated_test_start_date": self.evaluated_test_start_date.isoformat(),
            "evaluated_test_end_date": self.evaluated_test_end_date.isoformat(),
            "files": {
                name: self.files[name].to_dict() for name in sorted(self.files)
            },
            "library_versions": dict(sorted(self.library_versions.items())),
            "reason_codes": list(self.reason_codes),
            "git_commit": self.git_commit,
        }

    def _content(self) -> dict[str, object]:
        return {
            **self._identity_content(),
            "created_at": self.created_at.isoformat(),
        }

    @property
    def manifest_sha256(self) -> str:
        encoded = json.dumps(
            self._identity_content(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self._content(), "manifest_sha256": self.manifest_sha256}

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, object]
    ) -> "TwseResearchModelBundleManifest":
        files_value = value.get("files")
        if not isinstance(files_value, Mapping):
            raise ValueError("bundle manifest files must be a mapping")
        libraries = value.get("library_versions")
        if not isinstance(libraries, Mapping):
            raise ValueError("library_versions must be a mapping")
        locked_holdout_executed = value.get("locked_holdout_executed")
        if not isinstance(locked_holdout_executed, bool):
            raise ValueError("locked_holdout_executed must be a boolean")
        manifest = cls(
            contract_version=_non_empty(value.get("contract_version"), "contract_version"),
            system_status=_non_empty(value.get("system_status"), "system_status"),
            selection_policy=_non_empty(value.get("selection_policy"), "selection_policy"),
            locked_holdout_executed=locked_holdout_executed,
            model_version=_non_empty(value.get("model_version"), "model_version"),
            horizon=_integer(value.get("horizon", 0), "horizon"),
            fold_number=_integer(value.get("fold_number", -1), "fold_number"),
            feature_schema_hash=_non_empty(value.get("feature_schema_hash"), "feature_schema_hash"),
            input_artifact_sha256=_non_empty(value.get("input_artifact_sha256"), "input_artifact_sha256"),
            source_hash=_non_empty(value.get("source_hash"), "source_hash"),
            dataset_snapshot_id=_non_empty(value.get("dataset_snapshot_id"), "dataset_snapshot_id"),
            label_version=_non_empty(value.get("label_version"), "label_version"),
            benchmark_id=_non_empty(value.get("benchmark_id"), "benchmark_id"),
            benchmark_version=_non_empty(value.get("benchmark_version"), "benchmark_version"),
            cost_profile_version=_non_empty(value.get("cost_profile_version"), "cost_profile_version"),
            random_seed=_integer(value.get("random_seed", 0), "random_seed"),
            feature_names=tuple(str(item) for item in _sequence(value, "feature_names")),
            direction_classes=tuple(str(item) for item in _sequence(value, "direction_classes")),
            training_start_date=date.fromisoformat(_non_empty(value.get("training_start_date"), "training_start_date")),
            training_end_date=date.fromisoformat(_non_empty(value.get("training_end_date"), "training_end_date")),
            calibration_start_date=date.fromisoformat(_non_empty(value.get("calibration_start_date"), "calibration_start_date")),
            calibration_end_date=date.fromisoformat(_non_empty(value.get("calibration_end_date"), "calibration_end_date")),
            evaluated_test_start_date=date.fromisoformat(_non_empty(value.get("evaluated_test_start_date"), "evaluated_test_start_date")),
            evaluated_test_end_date=date.fromisoformat(_non_empty(value.get("evaluated_test_end_date"), "evaluated_test_end_date")),
            created_at=datetime.fromisoformat(_non_empty(value.get("created_at"), "created_at")),
            files={
                str(name): BundleFileRecord.from_mapping(record)
                for name, record in files_value.items()
                if isinstance(record, Mapping)
            },
            library_versions={str(name): str(version) for name, version in libraries.items()},
            reason_codes=tuple(str(item) for item in _sequence(value, "reason_codes")),
            git_commit=(str(value["git_commit"]) if value.get("git_commit") is not None else None),
        )
        supplied_hash = _non_empty(value.get("manifest_sha256"), "manifest_sha256")
        if supplied_hash != manifest.manifest_sha256:
            raise ValueError("model bundle manifest hash mismatch")
        return manifest


def _sequence(value: Mapping[str, object], field_name: str) -> Sequence[object]:
    candidate = value.get(field_name)
    if not isinstance(candidate, Sequence) or isinstance(candidate, (str, bytes)):
        raise ValueError(f"{field_name} must be a sequence")
    return candidate


__all__ = [
    "BUNDLE_FILE_NAMES",
    "BundleFileRecord",
    "MECHANICAL_LAST_FOLD_POLICY",
    "TWSE_RESEARCH_BUNDLE_CONTRACT_VERSION",
    "TwseResearchModelBundleManifest",
]
