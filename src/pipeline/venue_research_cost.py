"""Validate and serialize the cost identity already used by prepared labels."""

from __future__ import annotations

from dataclasses import dataclass

from src.trading.transaction_cost import TransactionCostModel

from .contracts import PipelineContext
from .research_dataset import PreparedResearchDataset


@dataclass(frozen=True)
class ResearchCostIdentity:
    version: str
    profile: str


def resolve_research_cost_identity(
    dataset: PreparedResearchDataset,
    context: PipelineContext,
) -> ResearchCostIdentity | None:
    version = dataset.provenance["cost_profile_version"]
    config_version, separator, profile = version.rpartition(":")
    if (
        separator != ":"
        or config_version != context.config.cost.profile_version
        or profile not in TransactionCostModel.PROFILE_MULTIPLIERS
    ):
        return None
    return ResearchCostIdentity(version=version, profile=profile)


def research_cost_metadata(
    context: PipelineContext,
    identity: ResearchCostIdentity,
) -> dict[str, object]:
    cost = context.config.cost
    return {
        "asset_type": cost.asset_type,
        "commission_rate": cost.commission_rate,
        "commission_discount": cost.commission_discount,
        "minimum_fee": cost.minimum_fee,
        "sell_tax_rate": cost.sell_tax_rate,
        "estimated_order_notional_ntd": cost.estimated_order_notional_ntd,
        "spread_model": cost.spread_model,
        "slippage_scenario": cost.slippage_scenario,
        "market_impact_parameter": cost.market_impact_parameter,
        "max_adv_participation": cost.max_adv_participation,
        "cost_profile": identity.profile,
        "cost_profile_version": identity.version,
        "cost_profile_multiplier": float(
            TransactionCostModel.PROFILE_MULTIPLIERS[identity.profile]
        ),
    }


__all__ = [
    "ResearchCostIdentity",
    "research_cost_metadata",
    "resolve_research_cost_identity",
]
