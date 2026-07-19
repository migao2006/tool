"""Versioned, fail-closed contracts for TWSE research model outputs."""

# pyright: reportAny=false, reportExplicitAny=false, reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false, reportUnusedCallResult=false

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from math import isclose, isfinite
from typing import Any

from src.core.horizon import require_production_horizon
from src.core.json_value import require_aware_datetime, to_json_safe
from src.core.research_prediction_contract import (
    RESEARCH_PREDICTION_CONTRACT_VERSION,
)
from src.decision.decision_policy import DECISION_GATE_ORDER

from .twse_research_decision_contracts import ResearchDecisionGate


RESEARCH_EVALUATION_SCOPES = (
    "OUT_OF_SAMPLE_TEST",
    "DAILY_RESEARCH_INFERENCE",
    "RETROSPECTIVE_RESEARCH_INFERENCE",
)


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} is required")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")


@dataclass(frozen=True)
class TwseOosResearchPrediction:
    """One research-only prediction row.

    The legacy class name is retained for compatibility.  ``evaluation_scope``
    distinguishes untouched OOS evaluation from bundle-backed inference and is
    always serialized for downstream auditing.
    """

    symbol: str
    decision_date: date
    decision_at: datetime
    horizon: int
    fold_number: int
    model_raw_score: float
    rank_score: float
    global_rank: int
    global_rank_percentile: float
    calibrated_p_up: float
    calibrated_p_neutral: float
    calibrated_p_down: float
    calibration_version: str
    gross_q10: float
    gross_q50: float
    gross_q90: float
    net_q10: float
    net_q50: float
    net_q90: float
    interval_width: float
    calibration_status: str
    quantile_crossing_before_calibration: bool
    estimated_round_trip_cost: float
    latest_available_at: datetime
    data_quality_status: str
    reason_codes: tuple[str, ...]
    industry: str | None = None
    adv20_ntd: float | None = None
    maximum_order_notional_ntd: float | None = None
    market: str = "TWSE"
    evaluation_scope: str = "OUT_OF_SAMPLE_TEST"
    gates: tuple[ResearchDecisionGate, ...] = ()

    def __post_init__(self) -> None:
        _ = require_production_horizon(self.horizon)
        _require_text(self.symbol, "symbol")
        require_aware_datetime(self.decision_at, "decision_at")
        require_aware_datetime(self.latest_available_at, "latest_available_at")
        if self.market != "TWSE":
            raise ValueError("the first research publisher accepts TWSE rows only")
        if self.evaluation_scope not in RESEARCH_EVALUATION_SCOPES:
            raise ValueError("research prediction evaluation_scope is unsupported")
        if self.decision_at.date() != self.decision_date:
            raise ValueError("decision_at date must match decision_date")
        if self.latest_available_at > self.decision_at:
            raise ValueError("latest_available_at cannot exceed decision_at")
        if self.fold_number < 0 or self.global_rank < 1:
            raise ValueError("fold_number must be non-negative and rank positive")
        if not isfinite(self.rank_score) or not 0 <= self.rank_score <= 100:
            raise ValueError("rank_score must be a 0-100 percentile")
        if not isfinite(self.global_rank_percentile) or not (
            0 <= self.global_rank_percentile <= 1
        ):
            raise ValueError("global_rank_percentile must be within [0, 1]")
        if not isclose(
            self.rank_score,
            100 * self.global_rank_percentile,
            abs_tol=1e-9,
        ):
            raise ValueError("rank_score must equal 100 * global_rank_percentile")
        probabilities = (
            self.calibrated_p_up,
            self.calibrated_p_neutral,
            self.calibrated_p_down,
        )
        if any(not isfinite(value) or not 0 <= value <= 1 for value in probabilities):
            raise ValueError("calibrated probabilities must be within [0, 1]")
        if not isclose(sum(probabilities), 1.0, abs_tol=1e-6):
            raise ValueError("calibrated probabilities must sum to one")
        if not isfinite(self.model_raw_score):
            raise ValueError("model_raw_score must be finite")
        if not self.gross_q10 <= self.gross_q50 <= self.gross_q90:
            raise ValueError("gross quantiles must be monotonic")
        if not self.net_q10 <= self.net_q50 <= self.net_q90:
            raise ValueError("net quantiles must be monotonic")
        if not isclose(
            self.interval_width,
            self.net_q90 - self.net_q10,
            abs_tol=1e-9,
        ):
            raise ValueError("interval_width must equal net_q90 - net_q10")
        if not isfinite(self.estimated_round_trip_cost) or (
            self.estimated_round_trip_cost < 0
        ):
            raise ValueError("estimated_round_trip_cost must be non-negative")
        if self.adv20_ntd is not None and (
            not isfinite(self.adv20_ntd) or self.adv20_ntd <= 0
        ):
            raise ValueError("adv20_ntd must be positive when present")
        if self.maximum_order_notional_ntd is not None and (
            not isfinite(self.maximum_order_notional_ntd)
            or self.maximum_order_notional_ntd <= 0
        ):
            raise ValueError("maximum_order_notional_ntd must be positive when present")
        if self.data_quality_status not in {"PASS", "WARN"}:
            raise ValueError("research data quality must be PASS or WARN")
        _require_text(self.calibration_version, "calibration_version")
        _require_text(self.calibration_status, "calibration_status")
        if not self.reason_codes or any(not value for value in self.reason_codes):
            raise ValueError("research limitations must be preserved as reason_codes")
        if (
            self.gates
            and tuple(gate.gate for gate in self.gates) != DECISION_GATE_ORDER
        ):
            raise ValueError("research decision gates must follow the complete order")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "market": self.market,
            "industry": self.industry,
            "decision_date": self.decision_date,
            "decision_at": self.decision_at,
            "horizon": self.horizon,
            "fold_number": self.fold_number,
            "evaluation_scope": self.evaluation_scope,
            "model_raw_score": self.model_raw_score,
            "rank_score": self.rank_score,
            "global_rank": self.global_rank,
            "global_rank_percentile": self.global_rank_percentile,
            "calibrated_p_up": self.calibrated_p_up,
            "calibrated_p_neutral": self.calibrated_p_neutral,
            "calibrated_p_down": self.calibrated_p_down,
            "calibration_version": self.calibration_version,
            "gross_q10": self.gross_q10,
            "gross_q50": self.gross_q50,
            "gross_q90": self.gross_q90,
            "net_q10": self.net_q10,
            "net_q50": self.net_q50,
            "net_q90": self.net_q90,
            "interval_width": self.interval_width,
            "calibration_status": self.calibration_status,
            "quantile_crossing_before_calibration": (
                self.quantile_crossing_before_calibration
            ),
            "estimated_round_trip_cost": self.estimated_round_trip_cost,
            "adv20_ntd": self.adv20_ntd,
            "maximum_order_notional_ntd": self.maximum_order_notional_ntd,
            "latest_available_at": self.latest_available_at,
            "data_quality_status": self.data_quality_status,
            "reason_codes": self.reason_codes,
        }
        if self.gates:
            payload["decision"] = "NO_TRADE"
            payload["gates"] = [gate.to_dict() for gate in self.gates]
        return to_json_safe(payload, "prediction")


@dataclass(frozen=True)
class TwseResearchPredictionSnapshot:
    as_of_date: date
    decision_at: datetime
    horizon: int
    predictions: tuple[TwseOosResearchPrediction, ...]
    model_version: str
    feature_schema_hash: str
    dataset_snapshot_id: str
    source_hash: str
    input_artifact_sha256: str
    label_version: str
    benchmark_id: str
    benchmark_version: str
    cost_profile_version: str
    training_end_date: date
    model_metadata: Mapping[str, Any]
    cost_metadata: Mapping[str, Any]
    validation: Mapping[str, Any]
    reason_codes: tuple[str, ...]
    system_status: str = "RESEARCH_ONLY"
    artifact_contract_version: str = RESEARCH_PREDICTION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _ = require_production_horizon(self.horizon)
        require_aware_datetime(self.decision_at, "decision_at")
        if self.artifact_contract_version != RESEARCH_PREDICTION_CONTRACT_VERSION:
            raise ValueError("unsupported research prediction contract version")
        if self.system_status != "RESEARCH_ONLY":
            raise ValueError("research prediction snapshots cannot be promoted")
        if not self.predictions:
            raise ValueError("research prediction snapshot cannot be empty")
        if self.training_end_date >= self.as_of_date:
            raise ValueError("training_end_date must precede the research as_of_date")
        required_text = {
            "model_version": self.model_version,
            "label_version": self.label_version,
            "benchmark_id": self.benchmark_id,
            "benchmark_version": self.benchmark_version,
            "cost_profile_version": self.cost_profile_version,
        }
        for field_name, value in required_text.items():
            _require_text(value, field_name)
        for field_name, value in {
            "feature_schema_hash": self.feature_schema_hash,
            "dataset_snapshot_id": self.dataset_snapshot_id,
            "source_hash": self.source_hash,
            "input_artifact_sha256": self.input_artifact_sha256,
        }.items():
            _require_sha256(value, field_name)
        if not self.model_metadata or not self.cost_metadata or not self.validation:
            raise ValueError("model, cost, and walk-forward metadata are required")
        to_json_safe(self.model_metadata, "model_metadata")
        to_json_safe(self.cost_metadata, "cost_metadata")
        to_json_safe(self.validation, "validation")
        if not self.reason_codes or any(not value for value in self.reason_codes):
            raise ValueError("research snapshot limitations must be explicit")
        symbols: set[str] = set()
        ranks: set[int] = set()
        evaluation_scopes: set[str] = set()
        for prediction in self.predictions:
            if prediction.horizon != self.horizon:
                raise ValueError("prediction horizon does not match snapshot")
            if prediction.decision_date != self.as_of_date:
                raise ValueError("prediction date does not match snapshot")
            if prediction.decision_at != self.decision_at:
                raise ValueError("prediction decision_at does not match snapshot")
            if prediction.symbol in symbols or prediction.global_rank in ranks:
                raise ValueError("snapshot symbols and global ranks must be unique")
            symbols.add(prediction.symbol)
            ranks.add(prediction.global_rank)
            evaluation_scopes.add(prediction.evaluation_scope)
        if len(evaluation_scopes) != 1:
            raise ValueError("one snapshot cannot mix research evaluation scopes")

    def _content(self) -> dict[str, Any]:
        return to_json_safe(
            {
                "artifact_contract_version": self.artifact_contract_version,
                "system_status": self.system_status,
                "as_of_date": self.as_of_date,
                "decision_at": self.decision_at,
                "horizon": self.horizon,
                "predictions": [value.to_dict() for value in self.predictions],
                "model_version": self.model_version,
                "feature_schema_hash": self.feature_schema_hash,
                "dataset_snapshot_id": self.dataset_snapshot_id,
                "source_hash": self.source_hash,
                "input_artifact_sha256": self.input_artifact_sha256,
                "label_version": self.label_version,
                "benchmark_id": self.benchmark_id,
                "benchmark_version": self.benchmark_version,
                "cost_profile_version": self.cost_profile_version,
                "training_end_date": self.training_end_date,
                "model_metadata": self.model_metadata,
                "cost_metadata": self.cost_metadata,
                "validation": self.validation,
                "reason_codes": self.reason_codes,
            },
            "snapshot",
        )

    @property
    def snapshot_sha256(self) -> str:
        encoded = json.dumps(
            self._content(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self._content(), "snapshot_sha256": self.snapshot_sha256}


__all__ = [
    "RESEARCH_EVALUATION_SCOPES",
    "RESEARCH_PREDICTION_CONTRACT_VERSION",
    "TwseOosResearchPrediction",
    "TwseResearchPredictionSnapshot",
]
