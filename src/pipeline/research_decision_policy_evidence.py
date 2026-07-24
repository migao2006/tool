"""Point-in-time contract for non-model Decision Policy evidence."""

from __future__ import annotations

# pyright: reportAny=false, reportExplicitAny=false

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from hashlib import sha256
import json
from math import isclose, isfinite
from typing import Any, cast

from src.core.json_value import require_aware_datetime, to_json_safe


EVIDENCE_CONTRACT_VERSION = "decision-policy-required-evidence.v1"
EVIDENCE_STATUSES = frozenset({"AVAILABLE", "MISSING"})
SUPPORTED_MARKETS = frozenset({"TWSE", "TPEX"})


class RequiredEvidenceCategory(str, Enum):
    TRADABILITY = "TRADABILITY"
    MARKET_EXPOSURE = "MARKET_EXPOSURE"
    POSITION_LIMITS = "POSITION_LIMITS"


CATEGORY_GATE = {
    RequiredEvidenceCategory.TRADABILITY: "tradability_gate",
    RequiredEvidenceCategory.MARKET_EXPOSURE: "market_exposure_cap",
    RequiredEvidenceCategory.POSITION_LIMITS: "position_capacity_limits",
}

_TRADABILITY_FIELDS = frozenset(
    {
        "trading_status",
        "attention_flag",
        "disposal_flag",
        "altered_trading_method_flag",
        "full_cash_delivery_flag",
        "periodic_auction_flag",
        "suspended_flag",
    }
)
_MARKET_FIELDS = frozenset(
    {
        "calibrated_p_up",
        "calibrated_p_neutral",
        "calibrated_p_down",
        "market_regime",
        "forecast_market_volatility",
        "model_version",
        "training_end_date",
    }
)
_POSITION_FIELDS = frozenset(
    {
        "portfolio_policy_version",
        "portfolio_state_id",
        "maximum_single_name_weight",
        "maximum_industry_weight",
        "maximum_adv_participation",
        "proposed_weight",
        "resulting_industry_weight",
        "proposed_adv_participation",
    }
)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric")
    parsed = float(value)
    if not isfinite(parsed):
        raise ValueError(f"{field_name} must be finite")
    return parsed


def _date(value: object, field_name: str) -> date:
    if isinstance(value, datetime):
        raise ValueError(f"{field_name} must be an ISO date")
    if isinstance(value, date):
        return value
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO date") from error
    if parsed.isoformat() != str(value):
        raise ValueError(f"{field_name} must be an ISO date")
    return parsed


def _aware_datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{field_name} must be an ISO datetime") from error
    require_aware_datetime(parsed, field_name)
    return parsed


def _validate_tradability(value: object, details: Mapping[str, Any]) -> None:
    if not isinstance(value, bool):
        raise ValueError("tradability evidence value must be boolean")
    if set(details) != _TRADABILITY_FIELDS:
        raise ValueError("tradability evidence fields are incomplete")
    trading_status = _required_text(details.get("trading_status"), "trading_status")
    flags = {name: details.get(name) for name in _TRADABILITY_FIELDS if name != "trading_status"}
    if any(not isinstance(flag, bool) for flag in flags.values()):
        raise ValueError("tradability evidence flags must be boolean")
    expected = (
        trading_status == "ACTIVE"
        and not cast(bool, flags["disposal_flag"])
        and not cast(bool, flags["altered_trading_method_flag"])
        and not cast(bool, flags["full_cash_delivery_flag"])
        and not cast(bool, flags["periodic_auction_flag"])
        and not cast(bool, flags["suspended_flag"])
    )
    if value != expected:
        raise ValueError("tradability evidence value does not match its state")


def _validate_market_exposure(
    value: object,
    details: Mapping[str, Any],
    effective_date: date,
) -> None:
    exposure = _number(value, "market exposure evidence value")
    if not 0 <= exposure <= 1:
        raise ValueError("market exposure evidence value must be within [0, 1]")
    if set(details) != _MARKET_FIELDS:
        raise ValueError("market exposure evidence fields are incomplete")
    probabilities = tuple(
        _number(details.get(name), name)
        for name in (
            "calibrated_p_up",
            "calibrated_p_neutral",
            "calibrated_p_down",
        )
    )
    if any(not 0 <= probability <= 1 for probability in probabilities) or not isclose(
        sum(probabilities), 1.0, abs_tol=1e-6
    ):
        raise ValueError("market exposure probabilities are invalid")
    volatility = _number(
        details.get("forecast_market_volatility"),
        "forecast_market_volatility",
    )
    if volatility < 0:
        raise ValueError("forecast_market_volatility cannot be negative")
    _required_text(details.get("market_regime"), "market_regime")
    _required_text(details.get("model_version"), "model_version")
    if _date(details.get("training_end_date"), "training_end_date") >= effective_date:
        raise ValueError("market model training must precede its effective date")


def _validate_position_limits(value: object, details: Mapping[str, Any]) -> None:
    if not isinstance(value, bool):
        raise ValueError("position-limit evidence value must be boolean")
    if set(details) != _POSITION_FIELDS:
        raise ValueError("position-limit evidence fields are incomplete")
    _required_text(details.get("portfolio_policy_version"), "portfolio_policy_version")
    _required_text(details.get("portfolio_state_id"), "portfolio_state_id")
    maximum_single = _number(
        details.get("maximum_single_name_weight"),
        "maximum_single_name_weight",
    )
    maximum_industry = _number(
        details.get("maximum_industry_weight"),
        "maximum_industry_weight",
    )
    maximum_adv = _number(
        details.get("maximum_adv_participation"),
        "maximum_adv_participation",
    )
    proposed = _number(details.get("proposed_weight"), "proposed_weight")
    resulting_industry = _number(
        details.get("resulting_industry_weight"),
        "resulting_industry_weight",
    )
    proposed_adv = _number(
        details.get("proposed_adv_participation"),
        "proposed_adv_participation",
    )
    if any(
        not 0 <= item <= 1
        for item in (
            maximum_single,
            maximum_industry,
            maximum_adv,
            proposed,
            resulting_industry,
            proposed_adv,
        )
    ):
        raise ValueError("position-limit weights must be within [0, 1]")
    expected = (
        proposed <= maximum_single
        and resulting_industry <= maximum_industry
        and proposed_adv <= maximum_adv
    )
    if value != expected:
        raise ValueError("position-limit evidence value does not match its state")


@dataclass(frozen=True)
class RequiredPolicyEvidence:
    category: RequiredEvidenceCategory
    status: str
    value: bool | float | None
    source: str | None
    market: str
    symbol: str | None
    effective_date: date | None
    available_at: datetime | None
    publication_id: str | None
    validation_result: str
    reason_code: str
    details: Mapping[str, Any]

    def __post_init__(self) -> None:
        category = RequiredEvidenceCategory(self.category)
        object.__setattr__(self, "category", category)
        market = self.market.strip().upper()
        if market not in SUPPORTED_MARKETS:
            raise ValueError("required evidence market is unsupported")
        object.__setattr__(self, "market", market)
        if self.status not in EVIDENCE_STATUSES:
            raise ValueError("required evidence status is unsupported")
        if category is RequiredEvidenceCategory.MARKET_EXPOSURE:
            if self.symbol is not None:
                raise ValueError("market exposure evidence cannot contain a symbol")
        elif not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("security-specific evidence requires a symbol")
        if self.status == "AVAILABLE":
            source = _required_text(self.source, "evidence source")
            publication_id = _required_text(
                self.publication_id,
                "evidence publication_id",
            )
            if self.effective_date is None or self.available_at is None:
                raise ValueError("available evidence requires effective and availability dates")
            require_aware_datetime(self.available_at, "evidence available_at")
            if self.validation_result != "PASS" or self.reason_code != "PASS":
                raise ValueError("available evidence requires a PASS validation result")
            object.__setattr__(self, "source", source)
            object.__setattr__(self, "publication_id", publication_id)
            if category is RequiredEvidenceCategory.TRADABILITY:
                _validate_tradability(self.value, self.details)
            elif category is RequiredEvidenceCategory.MARKET_EXPOSURE:
                _validate_market_exposure(
                    self.value,
                    self.details,
                    self.effective_date,
                )
            else:
                _validate_position_limits(self.value, self.details)
        else:
            if self.value is not None:
                raise ValueError("missing evidence cannot carry a value")
            if self.validation_result != "MISSING":
                raise ValueError("missing evidence requires validation_result=MISSING")
            _required_text(self.reason_code, "missing evidence reason_code")
            if self.reason_code == "PASS":
                raise ValueError("missing evidence reason_code cannot be PASS")
            if self.available_at is not None:
                require_aware_datetime(self.available_at, "evidence available_at")
        to_json_safe(dict(self.details), "evidence details")

    @classmethod
    def available(
        cls,
        *,
        category: RequiredEvidenceCategory,
        value: bool | float,
        source: str,
        market: str,
        symbol: str | None,
        effective_date: date,
        available_at: datetime,
        publication_id: str,
        details: Mapping[str, Any],
    ) -> RequiredPolicyEvidence:
        return cls(
            category=category,
            status="AVAILABLE",
            value=value,
            source=source,
            market=market,
            symbol=symbol,
            effective_date=effective_date,
            available_at=available_at,
            publication_id=publication_id,
            validation_result="PASS",
            reason_code="PASS",
            details=dict(details),
        )

    @classmethod
    def missing(
        cls,
        *,
        category: RequiredEvidenceCategory,
        market: str,
        symbol: str | None,
        reason_code: str,
        source: str | None = None,
        effective_date: date | None = None,
        available_at: datetime | None = None,
        publication_id: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> RequiredPolicyEvidence:
        return cls(
            category=category,
            status="MISSING",
            value=None,
            source=source,
            market=market,
            symbol=symbol,
            effective_date=effective_date,
            available_at=available_at,
            publication_id=publication_id,
            validation_result="MISSING",
            reason_code=reason_code,
            details=dict(details or {}),
        )

    @property
    def gate(self) -> str:
        return CATEGORY_GATE[self.category]

    def to_dict(self) -> dict[str, Any]:
        return to_json_safe(
            {
                "contract_version": EVIDENCE_CONTRACT_VERSION,
                "category": self.category.value,
                "status": self.status,
                "value": self.value,
                "source": self.source,
                "market": self.market,
                "symbol": self.symbol,
                "effective_date": self.effective_date,
                "available_at": self.available_at,
                "publication_id": self.publication_id,
                "validation_result": self.validation_result,
                "reason_code": self.reason_code,
                "details": dict(self.details),
            },
            "required policy evidence",
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> RequiredPolicyEvidence:
        if value.get("contract_version") != EVIDENCE_CONTRACT_VERSION:
            raise ValueError("required evidence contract version is unsupported")
        raw_details = value.get("details")
        if not isinstance(raw_details, Mapping):
            raise ValueError("required evidence details must be an object")
        category = RequiredEvidenceCategory(str(value.get("category")))
        raw_value = value.get("value")
        if raw_value is not None and not isinstance(raw_value, (bool, int, float)):
            raise ValueError("required evidence value is invalid")
        parsed_value: bool | float | None = (
            float(raw_value)
            if isinstance(raw_value, int) and not isinstance(raw_value, bool)
            else cast(bool | float | None, raw_value)
        )
        return cls(
            category=category,
            status=str(value.get("status")),
            value=parsed_value,
            source=cast(str | None, value.get("source")),
            market=str(value.get("market") or ""),
            symbol=cast(str | None, value.get("symbol")),
            effective_date=(
                None
                if value.get("effective_date") is None
                else _date(value.get("effective_date"), "effective_date")
            ),
            available_at=(
                None
                if value.get("available_at") is None
                else _aware_datetime(value.get("available_at"), "available_at")
            ),
            publication_id=cast(str | None, value.get("publication_id")),
            validation_result=str(value.get("validation_result") or ""),
            reason_code=str(value.get("reason_code") or ""),
            details=dict(cast(Mapping[str, Any], raw_details)),
        )


@dataclass(frozen=True)
class DecisionPolicyEvidenceSnapshot:
    market: str
    as_of_date: date
    decision_at: datetime
    evidence: tuple[RequiredPolicyEvidence, ...]
    publication_id: str
    horizon: int = 5
    system_status: str = "RESEARCH_ONLY"

    def __post_init__(self) -> None:
        market = self.market.strip().upper()
        if market not in SUPPORTED_MARKETS:
            raise ValueError("required evidence snapshot market is unsupported")
        object.__setattr__(self, "market", market)
        require_aware_datetime(self.decision_at, "evidence snapshot decision_at")
        if self.decision_at.date() != self.as_of_date:
            raise ValueError("evidence decision_at date must match as_of_date")
        if self.horizon != 5:
            raise ValueError("UNSUPPORTED_HORIZON")
        if self.system_status != "RESEARCH_ONLY":
            raise ValueError("required evidence snapshots must remain RESEARCH_ONLY")
        _required_text(self.publication_id, "evidence snapshot publication_id")
        if not self.evidence:
            raise ValueError("required evidence snapshot cannot be empty")
        keys: set[tuple[RequiredEvidenceCategory, str | None]] = set()
        for item in self.evidence:
            if item.market != market:
                raise ValueError("required evidence market does not match snapshot")
            key = (item.category, item.symbol)
            if key in keys:
                raise ValueError("required evidence category and identity must be unique")
            keys.add(key)
            if item.status == "AVAILABLE":
                if item.effective_date != self.as_of_date:
                    raise ValueError("available evidence must match the exact effective date")
                if item.available_at is None or item.available_at > self.decision_at:
                    raise ValueError("evidence available_at cannot exceed decision_at")
        market_count = sum(
            item.category is RequiredEvidenceCategory.MARKET_EXPOSURE for item in self.evidence
        )
        tradability_symbols = {
            item.symbol
            for item in self.evidence
            if item.category is RequiredEvidenceCategory.TRADABILITY
        }
        position_symbols = {
            item.symbol
            for item in self.evidence
            if item.category is RequiredEvidenceCategory.POSITION_LIMITS
        }
        if market_count != 1 or not tradability_symbols or tradability_symbols != position_symbols:
            raise ValueError("required evidence snapshot category coverage is incomplete")

    def get(
        self,
        category: RequiredEvidenceCategory,
        *,
        symbol: str | None,
    ) -> RequiredPolicyEvidence | None:
        normalized = RequiredEvidenceCategory(category)
        return next(
            (
                item
                for item in self.evidence
                if item.category is normalized and item.symbol == symbol
            ),
            None,
        )

    def require(
        self,
        category: RequiredEvidenceCategory,
        *,
        symbol: str | None,
    ) -> RequiredPolicyEvidence:
        item = self.get(category, symbol=symbol)
        if item is None:
            raise ValueError("required evidence record is missing")
        return item

    def _content(self) -> dict[str, Any]:
        ordered = sorted(
            self.evidence,
            key=lambda item: (item.category.value, item.symbol or ""),
        )
        return to_json_safe(
            {
                "contract_version": EVIDENCE_CONTRACT_VERSION,
                "market": self.market,
                "as_of_date": self.as_of_date,
                "decision_at": self.decision_at,
                "horizon": self.horizon,
                "evidence": [item.to_dict() for item in ordered],
                "publication_id": self.publication_id,
                "system_status": self.system_status,
            },
            "required evidence snapshot",
        )

    @property
    def snapshot_sha256(self) -> str:
        return sha256(
            json.dumps(
                self._content(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self._content(), "snapshot_sha256": self.snapshot_sha256}

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, object],
    ) -> DecisionPolicyEvidenceSnapshot:
        if value.get("contract_version") != EVIDENCE_CONTRACT_VERSION:
            raise ValueError("required evidence snapshot contract is unsupported")
        raw_evidence = value.get("evidence")
        if not isinstance(raw_evidence, list) or not raw_evidence:
            raise ValueError("required evidence snapshot rows are invalid")
        rows = tuple(
            RequiredPolicyEvidence.from_mapping(cast(Mapping[str, object], item))
            for item in raw_evidence
            if isinstance(item, Mapping)
        )
        if len(rows) != len(raw_evidence):
            raise ValueError("required evidence snapshot rows must be objects")
        snapshot = cls(
            market=str(value.get("market") or ""),
            as_of_date=_date(value.get("as_of_date"), "as_of_date"),
            decision_at=_aware_datetime(value.get("decision_at"), "decision_at"),
            horizon=int(cast(int | str, value.get("horizon"))),
            evidence=rows,
            publication_id=str(value.get("publication_id") or ""),
            system_status=str(value.get("system_status") or ""),
        )
        expected = str(value.get("snapshot_sha256") or "")
        if expected != snapshot.snapshot_sha256:
            raise ValueError("required evidence snapshot hash mismatch")
        return snapshot


__all__ = [
    "CATEGORY_GATE",
    "DecisionPolicyEvidenceSnapshot",
    "EVIDENCE_CONTRACT_VERSION",
    "RequiredEvidenceCategory",
    "RequiredPolicyEvidence",
]
