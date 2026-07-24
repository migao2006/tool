"""Versioned API envelope shared by inference services and the web client."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from math import isfinite
from typing import Any, Mapping

from src.calibration.status import (
    has_calibrated_interval_status,
    has_usable_version,
    has_valid_calibration_version,
)
from src.core.horizon import require_supported_horizon
from src.decision.decision_policy import DecisionPolicyStatus

from .market_output import MarketOutput
from .prediction_output import MARKETS, StockPredictionOutput


API_CONTRACT_VERSION = "prediction-snapshot.v1"
SYSTEM_STATUSES = {"PASS", "RESEARCH_ONLY", "FAIL"}


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _json_safe(value: Any, path: str = "value") -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{path} cannot contain NaN or infinity")
        return value
    if isinstance(value, datetime):
        _require_aware(value, path)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item, f"{path}.{key}") for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise TypeError(f"{path} contains unsupported JSON value {type(value).__name__}")


@dataclass(frozen=True)
class ExcludedSecurityOutput:
    as_of_date: date
    symbol: str
    name: str
    market: str
    horizon: int
    reason_codes: tuple[str, ...]
    latest_available_at: datetime | None = None

    def __post_init__(self) -> None:
        require_supported_horizon(self.horizon)
        if not self.symbol.strip() or not self.name.strip():
            raise ValueError("excluded security symbol and name are required")
        if self.market not in MARKETS:
            raise ValueError("excluded ordinary stock market must be LISTED or OTC")
        if not self.reason_codes:
            raise ValueError("excluded security requires at least one reason code")
        if self.latest_available_at is not None:
            _require_aware(self.latest_available_at, "latest_available_at")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "as_of_date": self.as_of_date.isoformat(),
            "symbol": self.symbol,
            "name": self.name,
            "market": self.market,
            "asset_type": "STOCK",
            "horizon": self.horizon,
            "data_quality_status": "HARD_FAIL",
            "data_quality_hard_fail": True,
            "decision": None,
            "decision_policy_status": DecisionPolicyStatus.HARD_FAIL.value,
            "reason_codes": list(self.reason_codes),
            "latest_available_at": (
                self.latest_available_at.isoformat()
                if self.latest_available_at is not None
                else None
            ),
        }
        return _json_safe(payload, "excluded")


@dataclass(frozen=True)
class PredictionSnapshotOutput:
    as_of_date: date
    decision_at: datetime
    horizon: int
    system_status: str
    predictions: tuple[StockPredictionOutput, ...] = ()
    market: MarketOutput | None = None
    watchlist: tuple[StockPredictionOutput, ...] = ()
    excluded: tuple[ExcludedSecurityOutput, ...] = ()
    stale: bool = False
    data_quality_hard_fail: bool = False
    reason_codes: tuple[str, ...] = ()
    model_version: str | None = None
    training_end_date: date | None = None
    cost_profile_version: str | None = None
    validation: Mapping[str, Any] = field(default_factory=dict)
    api_contract_version: str = API_CONTRACT_VERSION

    def __post_init__(self) -> None:
        require_supported_horizon(self.horizon)
        _require_aware(self.decision_at, "decision_at")
        if self.api_contract_version != API_CONTRACT_VERSION:
            raise ValueError("unsupported prediction snapshot API contract version")
        if self.system_status not in SYSTEM_STATUSES:
            raise ValueError("system_status must be PASS, RESEARCH_ONLY, or FAIL")

        all_predictions = (*self.predictions, *self.watchlist)
        for prediction in all_predictions:
            if (
                prediction.decision_policy_status == DecisionPolicyStatus.HARD_FAIL.value
                or prediction.data_quality_status == "HARD_FAIL"
            ):
                raise ValueError("HARD_FAIL rows must be published through excluded")
            if prediction.horizon != self.horizon:
                raise ValueError("prediction horizon does not match snapshot horizon")
            if prediction.as_of_date != self.as_of_date:
                raise ValueError("prediction as_of_date does not match snapshot")
            if prediction.decision_at != self.decision_at:
                raise ValueError("prediction decision_at does not match snapshot")
        for excluded in self.excluded:
            if excluded.horizon != self.horizon or excluded.as_of_date != self.as_of_date:
                raise ValueError("excluded security does not match snapshot date or horizon")
        included_keys = {
            (prediction.market, prediction.symbol.strip().upper()) for prediction in all_predictions
        }
        excluded_keys = {
            (excluded.market, excluded.symbol.strip().upper()) for excluded in self.excluded
        }
        if included_keys & excluded_keys:
            raise ValueError("included and excluded securities must be disjoint")

        if self.market is not None:
            if self.market.horizon != self.horizon:
                raise ValueError("market horizon does not match snapshot horizon")
            if self.market.as_of_date != self.as_of_date:
                raise ValueError("market as_of_date does not match snapshot")
            if self.market.decision_at != self.decision_at:
                raise ValueError("market decision_at does not match snapshot")

        if self.training_end_date is not None and self.training_end_date >= self.as_of_date:
            raise ValueError("training_end_date must be earlier than as_of_date")
        _json_safe(self.validation, "validation")

        if self.system_status == "PASS":
            if self.stale or self.data_quality_hard_fail:
                raise ValueError("PASS snapshot cannot be stale or have a hard fail")
            self._validate_formal_snapshot(all_predictions)

    def _validate_formal_snapshot(
        self,
        predictions: tuple[StockPredictionOutput, ...],
    ) -> None:
        if not self.predictions:
            raise ValueError("PASS snapshot requires a non-empty prediction universe")
        if self.market is None:
            raise ValueError("PASS snapshot requires market output")
        versions = {
            "model_version": self.model_version,
            "cost_profile_version": self.cost_profile_version,
        }
        for field_name, value in versions.items():
            if not has_usable_version(value):
                raise ValueError(f"PASS snapshot requires a valid {field_name}")
        if self.training_end_date is None:
            raise ValueError("PASS snapshot requires training_end_date")
        if not self.validation:
            raise ValueError("PASS snapshot requires validation results")
        for prediction in predictions:
            if (
                prediction.decision_policy_status != DecisionPolicyStatus.EVALUATED.value
                or prediction.data_quality_status != "PASS"
            ):
                raise ValueError("PASS snapshot requires evaluated policy evidence")
            if prediction.model_version != self.model_version:
                raise ValueError("prediction model_version does not match snapshot")
            if prediction.cost_profile_version != self.cost_profile_version:
                raise ValueError("prediction cost_profile_version does not match snapshot")
            if prediction.training_end_date != self.training_end_date:
                raise ValueError("prediction training_end_date does not match snapshot")
            if prediction.market_regime != self.market.market_regime:
                raise ValueError("prediction market_regime does not match market output")
            if (
                prediction.market_exposure_cap is None
                or not isfinite(prediction.market_exposure_cap)
                or abs(prediction.market_exposure_cap - self.market.market_exposure_cap) > 1e-9
            ):
                raise ValueError("prediction market_exposure_cap does not match market output")
            if not has_valid_calibration_version(prediction.calibration_version):
                raise ValueError("formal prediction requires calibrated direction probabilities")
            if not has_calibrated_interval_status(prediction.calibration_status):
                raise ValueError("formal prediction requires calibrated return intervals")
            required_values = {
                "industry": prediction.industry,
                "liquidity_bucket": prediction.liquidity_bucket,
                "forecast_volatility": prediction.forecast_volatility,
                "downside_risk": prediction.downside_risk,
                "adv20": prediction.adv20,
                "max_order_notional_ntd": prediction.max_order_notional_ntd,
                "max_single_position": prediction.max_single_position,
                "max_industry_position": prediction.max_industry_position,
                "cost_profile": prediction.cost_profile,
                "source_dates": prediction.source_dates,
                "gates": prediction.gates,
            }
            missing = [
                name
                for name, value in required_values.items()
                if value is None or value == "" or value == () or value == {}
            ]
            if missing:
                raise ValueError(
                    "formal prediction is missing API detail fields: " + ", ".join(missing)
                )

    def to_dict(self) -> dict[str, Any]:
        decision_counts = {
            "CANDIDATE": 0,
            "WATCH": 0,
            "NO_TRADE": 0,
            DecisionPolicyStatus.MISSING_REQUIRED_DATA.value: 0,
            DecisionPolicyStatus.VALIDATION_FAILED.value: 0,
            "HARD_FAIL": len(self.excluded),
        }
        for prediction in self.predictions:
            if (
                prediction.decision_policy_status == DecisionPolicyStatus.EVALUATED.value
                and prediction.decision in {"CANDIDATE", "WATCH", "NO_TRADE"}
            ):
                decision_counts[prediction.decision] += 1
            elif prediction.decision_policy_status in decision_counts:
                decision_counts[prediction.decision_policy_status] += 1
        payload = {
            "api_contract_version": self.api_contract_version,
            "as_of_date": self.as_of_date.isoformat(),
            "decision_at": self.decision_at.isoformat(),
            "horizon": self.horizon,
            "system_status": self.system_status,
            "stale": self.stale,
            "data_quality_hard_fail": self.data_quality_hard_fail,
            "reason_codes": list(self.reason_codes),
            "decision_counts": decision_counts,
            "market": self.market.to_dict() if self.market is not None else None,
            "predictions": [prediction.to_dict() for prediction in self.predictions],
            "watchlist": [prediction.to_dict() for prediction in self.watchlist],
            "excluded": [security.to_dict() for security in self.excluded],
            "model_version": self.model_version,
            "training_end_date": (
                self.training_end_date.isoformat() if self.training_end_date is not None else None
            ),
            "cost_profile_version": self.cost_profile_version,
            "validation": _json_safe(self.validation, "validation"),
        }
        return _json_safe(payload, "snapshot")
