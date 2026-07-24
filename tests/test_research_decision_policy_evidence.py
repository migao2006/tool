from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.pipeline.research_decision_policy_evidence import (
    DecisionPolicyEvidenceSnapshot,
    RequiredEvidenceCategory,
    RequiredPolicyEvidence,
)


AS_OF_DATE = date(2026, 7, 17)
DECISION_AT = datetime(2026, 7, 17, 17, tzinfo=ZoneInfo("Asia/Taipei"))
AVAILABLE_AT = datetime(2026, 7, 17, 16, tzinfo=ZoneInfo("Asia/Taipei"))


def _tradability(*, symbol: str = "2330", value: bool = True) -> RequiredPolicyEvidence:
    return RequiredPolicyEvidence.available(
        category=RequiredEvidenceCategory.TRADABILITY,
        value=value,
        source="TWSE_MOPS_SNAPSHOT",
        market="TWSE",
        symbol=symbol,
        effective_date=AS_OF_DATE,
        available_at=AVAILABLE_AT,
        publication_id="a" * 64,
        details={
            "trading_status": "ACTIVE",
            "attention_flag": False,
            "disposal_flag": not value,
            "altered_trading_method_flag": False,
            "full_cash_delivery_flag": False,
            "periodic_auction_flag": False,
            "suspended_flag": False,
        },
    )


def _market_exposure(*, value: float = 0.6) -> RequiredPolicyEvidence:
    return RequiredPolicyEvidence.available(
        category=RequiredEvidenceCategory.MARKET_EXPOSURE,
        value=value,
        source="TWSE_MARKET_MODEL",
        market="TWSE",
        symbol=None,
        effective_date=AS_OF_DATE,
        available_at=AVAILABLE_AT,
        publication_id="market-run-17",
        details={
            "calibrated_p_up": 0.55,
            "calibrated_p_neutral": 0.30,
            "calibrated_p_down": 0.15,
            "market_regime": "UPTREND_LOW_VOL_BROAD",
            "forecast_market_volatility": 0.012,
            "model_version": "twse-market-h5-v1",
            "training_end_date": "2026-07-16",
        },
    )


def _position_limits(*, symbol: str = "2330") -> RequiredPolicyEvidence:
    return RequiredPolicyEvidence.available(
        category=RequiredEvidenceCategory.POSITION_LIMITS,
        value=True,
        source="PORTFOLIO_POLICY_ENGINE",
        market="TWSE",
        symbol=symbol,
        effective_date=AS_OF_DATE,
        available_at=AVAILABLE_AT,
        publication_id=f"portfolio-state-{symbol}",
        details={
            "portfolio_policy_version": "portfolio-h5-v1",
            "portfolio_state_id": "portfolio-20260717-1600",
            "maximum_single_name_weight": 0.10,
            "maximum_industry_weight": 0.25,
            "maximum_adv_participation": 0.01,
            "proposed_weight": 0.04,
            "resulting_industry_weight": 0.18,
            "proposed_adv_participation": 0.005,
        },
    )


def test_required_evidence_snapshot_round_trips_falsy_authoritative_values() -> None:
    snapshot = DecisionPolicyEvidenceSnapshot(
        market="TWSE",
        as_of_date=AS_OF_DATE,
        decision_at=DECISION_AT,
        evidence=(
            _tradability(value=False),
            _market_exposure(value=0.0),
            _position_limits(),
        ),
        publication_id="decision-policy-evidence-run-17",
    )

    restored = DecisionPolicyEvidenceSnapshot.from_mapping(snapshot.to_dict())

    assert restored.snapshot_sha256 == snapshot.snapshot_sha256
    assert restored.require(RequiredEvidenceCategory.TRADABILITY, symbol="2330").value is False
    assert restored.require(RequiredEvidenceCategory.MARKET_EXPOSURE, symbol=None).value == 0.0


def test_market_exposure_parser_preserves_an_integer_zero_value() -> None:
    payload = _market_exposure(value=0.0).to_dict()
    payload["value"] = 0

    restored = RequiredPolicyEvidence.from_mapping(payload)

    assert restored.value == 0.0
    assert isinstance(restored.value, float)


def test_snapshot_requires_explicit_category_coverage_for_each_symbol() -> None:
    with pytest.raises(ValueError, match="category coverage"):
        DecisionPolicyEvidenceSnapshot(
            market="TWSE",
            as_of_date=AS_OF_DATE,
            decision_at=DECISION_AT,
            evidence=(_tradability(), _market_exposure()),
            publication_id="decision-policy-evidence-run-17",
        )


def test_available_evidence_rejects_lookahead_timestamp() -> None:
    with pytest.raises(ValueError, match="available_at cannot exceed decision_at"):
        DecisionPolicyEvidenceSnapshot(
            market="TWSE",
            as_of_date=AS_OF_DATE,
            decision_at=DECISION_AT,
            evidence=(
                RequiredPolicyEvidence.available(
                    category=RequiredEvidenceCategory.TRADABILITY,
                    value=True,
                    source="TWSE_MOPS_SNAPSHOT",
                    market="TWSE",
                    symbol="2330",
                    effective_date=AS_OF_DATE,
                    available_at=datetime(2026, 7, 17, 18, tzinfo=ZoneInfo("Asia/Taipei")),
                    publication_id="a" * 64,
                    details=_tradability().details,
                ),
            ),
            publication_id="decision-policy-evidence-run-17",
        )


def test_evidence_snapshot_rejects_cross_market_rows() -> None:
    tpex = RequiredPolicyEvidence.available(
        category=RequiredEvidenceCategory.TRADABILITY,
        value=True,
        source="TPEX_MOPS_SNAPSHOT",
        market="TPEX",
        symbol="6488",
        effective_date=AS_OF_DATE,
        available_at=AVAILABLE_AT,
        publication_id="b" * 64,
        details=_tradability().details,
    )

    with pytest.raises(ValueError, match="market"):
        DecisionPolicyEvidenceSnapshot(
            market="TWSE",
            as_of_date=AS_OF_DATE,
            decision_at=DECISION_AT,
            evidence=(tpex,),
            publication_id="decision-policy-evidence-run-17",
        )


def test_missing_evidence_has_no_value_and_preserves_reason() -> None:
    evidence = RequiredPolicyEvidence.missing(
        category=RequiredEvidenceCategory.POSITION_LIMITS,
        market="TWSE",
        symbol="2330",
        reason_code="POSITION_LIMIT_PRODUCER_UNAVAILABLE",
    )

    assert evidence.value is None
    assert evidence.validation_result == "MISSING"
    assert evidence.reason_code == "POSITION_LIMIT_PRODUCER_UNAVAILABLE"
