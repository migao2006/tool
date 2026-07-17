from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from src.core.horizon import require_supported_horizon


@dataclass(frozen=True)
class CostConfig:
    asset_type: str
    commission_rate: float
    commission_discount: float
    minimum_fee: float
    sell_tax_rate: float
    estimated_order_notional_ntd: float
    spread_model: str
    slippage_scenario: str
    market_impact_parameter: float
    max_adv_participation: float
    profile_version: str


@dataclass(frozen=True)
class RankConfig:
    objective: str
    relevance_levels: int
    eval_at: tuple[int, ...]
    lambdarank_truncation_level: int
    seed: int


@dataclass(frozen=True)
class DecisionConfig:
    minimum_p_up: float
    minimum_probability_spread: float
    minimum_net_q50: float
    maximum_net_q10_loss: float
    top_k: int


@dataclass(frozen=True)
class PortfolioConfig:
    maximum_single_name_weight: float
    maximum_industry_weight: float
    maximum_market_exposure: float
    minimum_holdings: int
    maximum_daily_turnover: float


@dataclass(frozen=True)
class ValidationConfig:
    minimum_training_years: int
    calibration_months: int
    test_months: int
    purge_trading_days: int
    locked_holdout_months: int
    step_months: int
    bootstrap_block_days: int


@dataclass(frozen=True)
class MvpConfig:
    horizon: int
    status: str
    listed_benchmark: str
    otc_benchmark: str
    cost: CostConfig
    rank: RankConfig
    decision: DecisionConfig
    portfolio: PortfolioConfig
    validation: ValidationConfig
    feature_available_at_policy: str
    extra: Mapping[str, object]

    def __post_init__(self) -> None:
        require_supported_horizon(self.horizon)
        if self.status not in {"PASS", "RESEARCH_ONLY", "FAIL"}:
            raise ValueError("status must be PASS, RESEARCH_ONLY, or FAIL")

