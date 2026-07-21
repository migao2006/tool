"""Auditable promotion manifest required before publishing a PASS result."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


REQUIRED_PROMOTION_CHECKS = (
    "data_quality",
    "model_metadata",
    "walk_forward",
    "locked_holdout",
    "ranking_acceptance",
    "direction_acceptance",
    "quantile_acceptance",
    "volatility_acceptance",
    "cost_backtest",
    "reproducibility",
)
REQUIRED_MODEL_ARTIFACTS = (
    "rank_model",
    "direction_model",
    "quantile_q10",
    "quantile_q50",
    "quantile_q90",
    "market_model",
    "volatility_model",
    "model_card",
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class PromotionAssessment:
    passed: bool
    reason_codes: tuple[str, ...]
    manifest_path: Path


@dataclass(frozen=True)
class PromotionBinding:
    horizon: int
    mode: str
    run_id: str
    source_hash: str
    model_version: str
    feature_schema_hash: str
    cost_profile_version: str
    training_end_date: date
    effective_date: date
    artifact_uris: Mapping[str, str]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _local_artifact_path(uri: str, artifact_root: Path) -> Path | None:
    if uri.startswith("file://"):
        candidate = Path(uri.removeprefix("file://"))
    elif "://" in uri:
        return None
    else:
        candidate = Path(uri)
    resolved = candidate.resolve()
    try:
        resolved.relative_to(artifact_root.resolve())
    except ValueError:
        return None
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def promotion_manifest_path(
    artifact_root: str | Path,
    *,
    horizon: int,
    mode: str,
    run_id: str,
) -> Path:
    if not _SAFE_IDENTIFIER_PATTERN.fullmatch(mode):
        raise ValueError("invalid promotion mode")
    if not _SAFE_IDENTIFIER_PATTERN.fullmatch(run_id):
        raise ValueError("invalid promotion run_id")
    return (
        Path(artifact_root)
        / f"horizon_{horizon}"
        / "promotion_manifests"
        / mode
        / f"{run_id}.json"
    )


def audit_promotion_manifest(
    artifact_root: str | Path,
    *,
    binding: PromotionBinding,
) -> PromotionAssessment:
    """Validate frozen promotion evidence against this exact pipeline run."""

    artifact_root_path = Path(artifact_root)
    try:
        path = promotion_manifest_path(
            artifact_root_path,
            horizon=binding.horizon,
            mode=binding.mode,
            run_id=binding.run_id,
        )
    except ValueError:
        fallback = artifact_root_path / f"horizon_{binding.horizon}"
        return PromotionAssessment(
            False,
            ("PROMOTION_IDENTITY_PATH_INVALID",),
            fallback,
        )
    if not path.is_file():
        return PromotionAssessment(False, ("PROMOTION_MANIFEST_MISSING",), path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return PromotionAssessment(False, ("PROMOTION_MANIFEST_INVALID",), path)
    if not isinstance(payload, dict):
        return PromotionAssessment(False, ("PROMOTION_MANIFEST_INVALID",), path)

    reasons: list[str] = []
    expected_identity = {
        "status": "PASS",
        "horizon": binding.horizon,
        "mode": binding.mode,
        "run_id": binding.run_id,
        "source_hash": binding.source_hash,
        "model_version": binding.model_version,
        "feature_schema_hash": binding.feature_schema_hash,
        "cost_profile_version": binding.cost_profile_version,
        "training_end_date": binding.training_end_date.isoformat(),
    }
    for field_name, expected_value in expected_identity.items():
        if payload.get(field_name) != expected_value:
            reasons.append(f"PROMOTION_IDENTITY_MISMATCH:{field_name}")
    if payload.get("locked_holdout_executed") is not True:
        reasons.append("PROMOTION_LOCKED_HOLDOUT_NOT_EXECUTED")
    if not _SHA256_PATTERN.fullmatch(binding.feature_schema_hash.lower()):
        reasons.append("PROMOTION_FEATURE_SCHEMA_HASH_INVALID")
    if binding.training_end_date > binding.effective_date:
        reasons.append("PROMOTION_TRAINING_END_DATE_IN_FUTURE")

    checks = _mapping(payload.get("checks"))
    for check in REQUIRED_PROMOTION_CHECKS:
        if check not in checks:
            reasons.append(f"PROMOTION_CHECK_MISSING:{check}")
        elif checks[check] != "PASS":
            reasons.append(f"PROMOTION_CHECK_NOT_PASS:{check}")

    artifact_hashes = _mapping(payload.get("artifact_hashes"))
    artifact_uris = _mapping(payload.get("artifact_uris"))
    for artifact in REQUIRED_MODEL_ARTIFACTS:
        expected_uri = binding.artifact_uris.get(artifact)
        if artifact_uris.get(artifact) != expected_uri:
            reasons.append(f"PROMOTION_ARTIFACT_URI_MISMATCH:{artifact}")
        digest = artifact_hashes.get(artifact)
        if digest is None:
            reasons.append(f"PROMOTION_ARTIFACT_MISSING:{artifact}")
        elif not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(
            digest.lower()
        ):
            reasons.append(f"PROMOTION_ARTIFACT_HASH_INVALID:{artifact}")
        if not isinstance(expected_uri, str):
            reasons.append(f"PROMOTION_RESULT_ARTIFACT_MISSING:{artifact}")
            continue
        try:
            artifact_path = _local_artifact_path(expected_uri, artifact_root_path)
        except (OSError, RuntimeError):
            reasons.append(f"PROMOTION_ARTIFACT_PATH_UNREADABLE:{artifact}")
            continue
        if artifact_path is None:
            reasons.append(f"PROMOTION_ARTIFACT_PATH_INVALID:{artifact}")
            continue
        try:
            artifact_is_file = artifact_path.is_file()
        except OSError:
            reasons.append(f"PROMOTION_ARTIFACT_READ_ERROR:{artifact}")
            continue
        if not artifact_is_file:
            reasons.append(f"PROMOTION_ARTIFACT_FILE_MISSING:{artifact}")
        elif isinstance(digest, str):
            try:
                actual_digest = _sha256(artifact_path)
            except OSError:
                reasons.append(f"PROMOTION_ARTIFACT_READ_ERROR:{artifact}")
            else:
                if actual_digest != digest.lower():
                    reasons.append(f"PROMOTION_ARTIFACT_HASH_MISMATCH:{artifact}")

    reason_codes = tuple(dict.fromkeys(reasons))
    return PromotionAssessment(not reason_codes, reason_codes, path)
