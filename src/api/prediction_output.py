from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from math import isclose, isfinite
from typing import Any

from src.calibration.status import (
    has_calibrated_interval_status,
    has_usable_version,
    has_valid_calibration_version,
)
from src.core.horizon import require_supported_horizon
from src.decision.decision_policy import DECISION_GATE_ORDER


DECISIONS = {"CANDIDATE", "WATCH", "NO_TRADE"}
MARKETS = {"LISTED", "OTC"}
DATA_QUALITY_STATUSES = {"PASS", "FAIL"}


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} is required")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class DecisionGateOutput:
    gate: str
    passed: bool
    actual: Any
    threshold: Any
    reason_code: str
    source_date: date | str | None = None

    def __post_init__(self) -> None:
        _require_text(self.gate, "gate")
        _require_text(self.reason_code, "reason_code")
        if not isinstance(self.passed, bool):
            raise TypeError("gate passed must be boolean")
        if isinstance(self.source_date, str):
            try:
                parsed_source_date = date.fromisoformat(self.source_date)
            except ValueError as error:
                raise ValueError("gate source_date must use YYYY-MM-DD") from error
            if parsed_source_date.isoformat() != self.source_date:
                raise ValueError("gate source_date must use YYYY-MM-DD")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if isinstance(self.source_date, date):
            payload["source_date"] = self.source_date.isoformat()
        return payload


@dataclass(frozen=True)
class StockPredictionOutput:
    as_of_date: date
    decision_at: datetime
    symbol: str
    name: str
    market: str
    industry: str | None
    horizon: int
    rank_score: float
    global_rank: int
    global_rank_percentile: float
    industry_rank: int | None
    industry_rank_percentile: float | None
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
    forecast_volatility: float | None
    downside_risk: float | None
    market_regime: str | None
    market_exposure_cap: float
    estimated_round_trip_cost: float
    data_quality_status: str
    decision: str
    reason_codes: tuple[str, ...]
    model_version: str
    feature_schema_hash: str
    cost_profile_version: str
    training_end_date: date
    source_dates: dict[str, date | str]
    latest_available_at: datetime
    asset_type: str = "STOCK"
    liquidity_bucket: str | None = None
    adv20: float | None = None
    max_order_notional_ntd: float | None = None
    max_single_position: float | None = None
    max_industry_position: float | None = None
    cost_profile: str | None = None
    previous_global_rank: int | None = None
    previous_decision: str | None = None
    gates: tuple[DecisionGateOutput, ...] = ()

    def __post_init__(self) -> None:
        require_supported_horizon(self.horizon)
        _require_aware(self.decision_at, "decision_at")
        _require_aware(self.latest_available_at, "latest_available_at")
        for field_name, value in (
            ("symbol", self.symbol),
            ("name", self.name),
            ("calibration_version", self.calibration_version),
            ("calibration_status", self.calibration_status),
            ("model_version", self.model_version),
            ("feature_schema_hash", self.feature_schema_hash),
            ("cost_profile_version", self.cost_profile_version),
        ):
            _require_text(value, field_name)
        if self.market not in MARKETS:
            raise ValueError("ordinary-stock output market must be LISTED or OTC")
        if self.asset_type != "STOCK":
            raise ValueError("ordinary-stock output asset_type must be STOCK")
        if self.decision not in DECISIONS:
            raise ValueError(f"unsupported decision: {self.decision}")
        if not isfinite(self.rank_score) or not 0 <= self.rank_score <= 100:
            raise ValueError("Rank Score must be a 0-100 cross-sectional percentile")
        if self.global_rank < 1:
            raise ValueError("global_rank must be positive")
        if (
            not isfinite(self.global_rank_percentile)
            or not 0 <= self.global_rank_percentile <= 1
        ):
            raise ValueError("global_rank_percentile must be within [0, 1]")
        if self.industry_rank is not None and self.industry_rank < 1:
            raise ValueError("industry_rank must be positive when provided")
        if self.industry_rank_percentile is not None and (
            not isfinite(self.industry_rank_percentile)
            or not 0 <= self.industry_rank_percentile <= 1
        ):
            raise ValueError("industry_rank_percentile must be within [0, 1]")
        probabilities = (
            self.calibrated_p_up,
            self.calibrated_p_neutral,
            self.calibrated_p_down,
        )
        if any(
            not isfinite(value) or value < 0 or value > 1 for value in probabilities
        ):
            raise ValueError("calibrated probabilities must be within [0, 1]")
        if not isclose(sum(probabilities), 1.0, abs_tol=1e-6):
            raise ValueError("calibrated probabilities must sum to 1")
        quantiles = (
            self.gross_q10,
            self.gross_q50,
            self.gross_q90,
            self.net_q10,
            self.net_q50,
            self.net_q90,
        )
        if any(not isfinite(value) for value in quantiles):
            raise ValueError("return quantiles must be finite")
        if not self.gross_q10 <= self.gross_q50 <= self.gross_q90:
            raise ValueError("gross quantiles must be monotonic")
        if not self.net_q10 <= self.net_q50 <= self.net_q90:
            raise ValueError("net quantiles must be monotonic")
        if not isfinite(self.interval_width) or not isclose(
            self.interval_width,
            self.net_q90 - self.net_q10,
            abs_tol=1e-9,
        ):
            raise ValueError("interval_width must equal net_q90 - net_q10")
        if (
            not isfinite(self.market_exposure_cap)
            or not 0 <= self.market_exposure_cap <= 1
        ):
            raise ValueError("market_exposure_cap must be within [0, 1]")
        if (
            not isfinite(self.estimated_round_trip_cost)
            or self.estimated_round_trip_cost < 0
        ):
            raise ValueError(
                "estimated_round_trip_cost must be finite and non-negative"
            )
        for field_name, value in (
            ("forecast_volatility", self.forecast_volatility),
            ("downside_risk", self.downside_risk),
            ("adv20", self.adv20),
            ("max_order_notional_ntd", self.max_order_notional_ntd),
        ):
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(f"{field_name} must be finite and non-negative")
        for field_name, value in (
            ("max_single_position", self.max_single_position),
            ("max_industry_position", self.max_industry_position),
        ):
            if value is not None and (not isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f"{field_name} must be within [0, 1]")
        if self.previous_global_rank is not None and self.previous_global_rank < 1:
            raise ValueError("previous_global_rank must be positive when provided")
        if (
            self.previous_decision is not None
            and self.previous_decision not in DECISIONS
        ):
            raise ValueError("previous_decision is invalid")
        if any(not isinstance(gate, DecisionGateOutput) for gate in self.gates):
            raise TypeError("gates must contain DecisionGateOutput values")
        if (
            self.gates
            and tuple(gate.gate for gate in self.gates) != DECISION_GATE_ORDER
        ):
            raise ValueError("gates must follow the complete decision policy order")
        if (
            self.decision == "CANDIDATE"
            and self.gates
            and any(not gate.passed for gate in self.gates)
        ):
            raise ValueError("CANDIDATE cannot contain a failed decision gate")
        if (
            self.decision == "CANDIDATE"
            and self.gates
            and any(gate.source_date is None for gate in self.gates)
        ):
            raise ValueError("CANDIDATE decision gates require source_date")
        if self.data_quality_status not in DATA_QUALITY_STATUSES:
            raise ValueError("data_quality_status must be PASS or FAIL")
        if self.latest_available_at > self.decision_at:
            raise ValueError("latest_available_at cannot exceed decision_at")
        if self.training_end_date >= self.as_of_date:
            raise ValueError("training_end_date must be earlier than as_of_date")
        for source_name, source_date in self.source_dates.items():
            if isinstance(source_date, str):
                try:
                    parsed_source_date = date.fromisoformat(source_date)
                except ValueError as error:
                    raise ValueError(
                        f"source date for {source_name} must use YYYY-MM-DD"
                    ) from error
            else:
                parsed_source_date = source_date
            if parsed_source_date > self.as_of_date:
                raise ValueError(
                    f"source date for {source_name} cannot exceed as_of_date"
                )

        if self.decision == "CANDIDATE":
            if not has_valid_calibration_version(self.calibration_version):
                raise ValueError(
                    "CANDIDATE requires an OOS direction calibration version"
                )
            if not has_calibrated_interval_status(self.calibration_status):
                raise ValueError("CANDIDATE requires calibrated return intervals")
            for field_name, value in (
                ("model_version", self.model_version),
                ("feature_schema_hash", self.feature_schema_hash),
                ("cost_profile_version", self.cost_profile_version),
            ):
                if not has_usable_version(value):
                    raise ValueError(f"CANDIDATE requires a valid {field_name}")
            if self.data_quality_status != "PASS":
                raise ValueError("CANDIDATE requires passing data quality")
            if self.market_exposure_cap <= 0:
                raise ValueError("CANDIDATE requires positive market exposure")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rank_score"] = payload.pop("rank_score")
        for key in (
            "as_of_date",
            "decision_at",
            "training_end_date",
            "latest_available_at",
        ):
            payload[key] = payload[key].isoformat()
        payload["reason_codes"] = list(self.reason_codes)
        payload["gates"] = [gate.to_dict() for gate in self.gates]
        payload["source_dates"] = {
            key: value.isoformat() if isinstance(value, date) else value
            for key, value in self.source_dates.items()
        }
        return payload
