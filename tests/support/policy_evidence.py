from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from src.pipeline.research_decision_policy_evidence import (
    RequiredEvidenceCategory,
    RequiredPolicyEvidence,
)


def required_policy_evidence(
    gate: str,
    *,
    as_of_date: date,
    decision_at: datetime,
    symbol: str,
    market: str = "TWSE",
    passed: bool = True,
    market_regime: str = "UPTREND_NORMAL_VOL",
    market_exposure_cap: float = 0.6,
    maximum_single_name_weight: float = 0.1,
    maximum_industry_weight: float = 0.25,
) -> dict[str, Any] | None:
    if gate == "tradability_gate":
        return RequiredPolicyEvidence.available(
            category=RequiredEvidenceCategory.TRADABILITY,
            value=passed,
            source=f"{market}_MOPS_SNAPSHOT",
            market=market,
            symbol=symbol,
            effective_date=as_of_date,
            available_at=decision_at,
            publication_id=f"security-state-{symbol}",
            details={
                "trading_status": "ACTIVE",
                "attention_flag": False,
                "disposal_flag": not passed,
                "altered_trading_method_flag": False,
                "full_cash_delivery_flag": False,
                "periodic_auction_flag": False,
                "suspended_flag": False,
            },
        ).to_dict()
    if gate == "market_exposure_cap":
        return RequiredPolicyEvidence.available(
            category=RequiredEvidenceCategory.MARKET_EXPOSURE,
            value=market_exposure_cap if passed else 0.0,
            source=f"MARKET_PREDICTION:{market.lower()}-market-h5-v1",
            market=market,
            symbol=None,
            effective_date=as_of_date,
            available_at=decision_at,
            publication_id=f"prediction-run-{market.lower()}",
            details={
                "calibrated_p_up": 0.6,
                "calibrated_p_neutral": 0.25,
                "calibrated_p_down": 0.15,
                "market_regime": market_regime,
                "forecast_market_volatility": 0.18,
                "model_version": f"{market.lower()}-market-h5-v1",
                "training_end_date": (as_of_date - timedelta(days=1)).isoformat(),
            },
        ).to_dict()
    if gate == "position_capacity_limits":
        return RequiredPolicyEvidence.available(
            category=RequiredEvidenceCategory.POSITION_LIMITS,
            value=passed,
            source="PORTFOLIO_POLICY_ENGINE",
            market=market,
            symbol=symbol,
            effective_date=as_of_date,
            available_at=decision_at,
            publication_id=f"portfolio-state-{symbol}",
            details={
                "portfolio_policy_version": "portfolio-h5-v1",
                "portfolio_state_id": f"portfolio-{as_of_date.isoformat()}",
                "maximum_single_name_weight": maximum_single_name_weight,
                "maximum_industry_weight": maximum_industry_weight,
                "maximum_adv_participation": 0.01,
                "proposed_weight": (
                    min(maximum_single_name_weight, 0.04)
                    if passed
                    else min(1.0, maximum_single_name_weight + 0.1)
                ),
                "resulting_industry_weight": min(maximum_industry_weight, 0.18),
                "proposed_adv_participation": 0.005,
            },
        ).to_dict()
    return None


__all__ = ["required_policy_evidence"]
