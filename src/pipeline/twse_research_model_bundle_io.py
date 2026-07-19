"""Atomic native-LightGBM persistence for the last TWSE research fold."""

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from importlib import import_module
import json
import os
from pathlib import Path
import shutil
from typing import Any, Protocol
from uuid import uuid4

from src.calibration.interval_calibrator import IntervalCalibrator
from src.calibration.probability_calibrator import ProbabilityCalibrator
from src.data.preprocessing import CrossSectionalMedianImputer

from .twse_research_model_bundle_contracts import (
    BUNDLE_FILE_NAMES,
    BundleFileRecord,
    TwseResearchModelBundleManifest,
)
from .twse_research_loaded_bundle import LoadedTwseResearchBundle
from .twse_research_model_bundle_state import (
    imputer_payload,
    interval_payload,
    probability_payload,
    read_imputer,
    read_interval,
    read_probability,
)


MANIFEST_FILENAME = "manifest.json"


class FittedBundleComponents(Protocol):
    @property
    def imputer(self) -> CrossSectionalMedianImputer: ...

    @property
    def rank_model(self) -> Any: ...

    @property
    def direction_model(self) -> Any: ...

    @property
    def probability_calibrator(self) -> ProbabilityCalibrator: ...

    @property
    def quantile_model(self) -> Any: ...

    @property
    def interval_calibrator(self) -> IntervalCalibrator: ...


@dataclass(frozen=True)
class WrittenTwseResearchBundle:
    bundle_dir: Path
    manifest_path: Path
    manifest: TwseResearchModelBundleManifest


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha_record(relative_path: str, payload: bytes) -> BundleFileRecord:
    return BundleFileRecord(
        relative_path=relative_path,
        sha256=sha256(payload).hexdigest(),
        byte_size=len(payload),
    )


def _native_booster(model: Any, component_name: str) -> Any:
    wrapper = getattr(model, "model", model)
    booster = getattr(wrapper, "booster_", None)
    if booster is None or not callable(getattr(booster, "model_to_string", None)):
        raise ValueError(f"{component_name} is not a fitted native LightGBM model")
    return booster


def _booster_payload(model: Any, component_name: str) -> bytes:
    booster = _native_booster(model, component_name)
    return (str(booster.model_to_string()).rstrip("\n") + "\n").encode("utf-8")


class TwseResearchBundleWriter:
    """Write an immutable bundle directory, verify it, then atomically publish."""

    def write(
        self,
        bundle_dir: Path,
        *,
        components: FittedBundleComponents,
        model_version: str,
        horizon: int,
        fold_number: int,
        feature_schema_hash: str,
        input_artifact_sha256: str,
        provenance: Mapping[str, str],
        random_seed: int,
        feature_names: Sequence[str],
        direction_classes: Sequence[str],
        training_dates: Sequence[date],
        calibration_dates: Sequence[date],
        evaluated_test_dates: Sequence[date],
        library_versions: Mapping[str, str],
        reason_codes: Sequence[str],
        git_commit: str | None = None,
    ) -> WrittenTwseResearchBundle:
        if bundle_dir.exists():
            raise FileExistsError("model bundle directory is immutable once published")
        required_provenance = (
            "dataset_snapshot_id",
            "source_hash",
            "label_version",
            "benchmark_id",
            "benchmark_version",
            "cost_profile_version",
        )
        missing = [name for name in required_provenance if not provenance.get(name)]
        if missing:
            raise ValueError("model bundle provenance is missing: " + ", ".join(missing))
        if not training_dates or not calibration_dates or not evaluated_test_dates:
            raise ValueError("all mechanical last-fold date blocks are required")

        quantile_models = getattr(components.quantile_model, "models", {})
        payloads = {
            "rank_booster": _booster_payload(components.rank_model, "rank_model"),
            "direction_booster": _booster_payload(
                components.direction_model, "direction_model"
            ),
            "q10_booster": _booster_payload(quantile_models.get(0.10), "q10_model"),
            "q50_booster": _booster_payload(quantile_models.get(0.50), "q50_model"),
            "q90_booster": _booster_payload(quantile_models.get(0.90), "q90_model"),
            "imputer_state": imputer_payload(components.imputer, feature_names),
            "probability_calibrator_state": probability_payload(
                components.probability_calibrator
            ),
            "interval_calibrator_state": interval_payload(
                components.interval_calibrator
            ),
        }
        records = {
            name: _sha_record(BUNDLE_FILE_NAMES[name], payload)
            for name, payload in payloads.items()
        }
        manifest = TwseResearchModelBundleManifest(
            model_version=model_version,
            horizon=horizon,
            fold_number=fold_number,
            feature_schema_hash=feature_schema_hash,
            input_artifact_sha256=input_artifact_sha256,
            source_hash=provenance["source_hash"],
            dataset_snapshot_id=provenance["dataset_snapshot_id"],
            label_version=provenance["label_version"],
            benchmark_id=provenance["benchmark_id"],
            benchmark_version=provenance["benchmark_version"],
            cost_profile_version=provenance["cost_profile_version"],
            random_seed=random_seed,
            feature_names=tuple(feature_names),
            direction_classes=tuple(direction_classes),
            training_start_date=min(training_dates),
            training_end_date=max(training_dates),
            calibration_start_date=min(calibration_dates),
            calibration_end_date=max(calibration_dates),
            evaluated_test_start_date=min(evaluated_test_dates),
            evaluated_test_end_date=max(evaluated_test_dates),
            created_at=datetime.now(timezone.utc),
            files=records,
            library_versions=dict(library_versions),
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            git_commit=git_commit,
        )
        bundle_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary = bundle_dir.with_name(f".{bundle_dir.name}.{uuid4().hex}.partial")
        temporary.mkdir()
        try:
            for name, payload in payloads.items():
                path = temporary / BUNDLE_FILE_NAMES[name]
                _ = path.write_bytes(payload)
                if path.read_bytes() != payload:
                    raise OSError(f"model bundle read-back failed for {name}")
            manifest_path = temporary / MANIFEST_FILENAME
            _ = manifest_path.write_bytes(_canonical_json(manifest.to_dict()))
            _ = TwseResearchBundleReader.read(temporary)
            os.replace(temporary, bundle_dir)
            loaded = TwseResearchBundleReader.read(bundle_dir)
            if loaded.manifest.manifest_sha256 != manifest.manifest_sha256:
                raise OSError("published model bundle manifest changed")
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        return WrittenTwseResearchBundle(
            bundle_dir=bundle_dir,
            manifest_path=bundle_dir / MANIFEST_FILENAME,
            manifest=manifest,
        )


class TwseResearchBundleReader:
    """Verify every byte before exposing native boosters or calibration state."""

    @classmethod
    def read(
        cls, bundle_dir: Path, manifest_path: Path | None = None
    ) -> LoadedTwseResearchBundle:
        root = bundle_dir.resolve(strict=True)
        selected_manifest = (manifest_path or (root / MANIFEST_FILENAME)).resolve(
            strict=True
        )
        if selected_manifest.parent != root:
            raise ValueError("model bundle manifest must be inside bundle_dir")
        raw_manifest = json.loads(selected_manifest.read_text(encoding="utf-8"))
        if not isinstance(raw_manifest, Mapping):
            raise ValueError("model bundle manifest must be a JSON object")
        manifest = TwseResearchModelBundleManifest.from_mapping(raw_manifest)
        paths: dict[str, Path] = {}
        for name, record in manifest.files.items():
            path = (root / record.relative_path).resolve(strict=True)
            if path.parent != root or not path.is_file():
                raise ValueError("model bundle artifact escaped its immutable root")
            payload = path.read_bytes()
            if len(payload) != record.byte_size or sha256(payload).hexdigest() != record.sha256:
                raise ValueError(f"model bundle artifact hash mismatch: {name}")
            paths[name] = path

        lightgbm = import_module("lightgbm")
        boosters = {
            name: lightgbm.Booster(model_file=str(paths[name]))
            for name in (
                "rank_booster",
                "direction_booster",
                "q10_booster",
                "q50_booster",
                "q90_booster",
            )
        }
        expected_features = len(manifest.feature_names) * 2
        if any(booster.num_feature() != expected_features for booster in boosters.values()):
            raise ValueError("native booster feature count does not match imputer contract")
        return LoadedTwseResearchBundle(
            manifest=manifest,
            imputer=read_imputer(paths["imputer_state"], manifest),
            rank_booster=boosters["rank_booster"],
            direction_booster=boosters["direction_booster"],
            quantile_boosters=(
                boosters["q10_booster"],
                boosters["q50_booster"],
                boosters["q90_booster"],
            ),
            probability_calibrator=read_probability(
                paths["probability_calibrator_state"]
            ),
            interval_calibrator=read_interval(
                paths["interval_calibrator_state"]
            ),
        )


__all__ = [
    "LoadedTwseResearchBundle",
    "TwseResearchBundleReader",
    "TwseResearchBundleWriter",
    "WrittenTwseResearchBundle",
]
