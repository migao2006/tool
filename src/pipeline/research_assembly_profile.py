"""Venue-specific constants for the shared five-session research assembler."""

from __future__ import annotations

from dataclasses import dataclass

from src.features.price_volume_schema import (
    PRICE_VOLUME_AVAILABILITY_MODES,
    PRICE_VOLUME_FEATURE_NAMES,
    RESEARCH_SCHEDULING_HINT_REASON,
    price_volume_feature_spec,
)


@dataclass(frozen=True)
class ResearchAssemblyProfile:
    market: str
    feature_schema_hash: str
    feature_names: tuple[str, ...]
    availability_modes: tuple[str, ...]
    scheduling_hint_reason: str
    label_version: str

    def __post_init__(self) -> None:
        if self.market not in {"TWSE", "TPEX"}:
            raise ValueError("research assembly supports only TWSE or TPEX")
        if not self.feature_schema_hash or not self.feature_names:
            raise ValueError("research assembly profile is incomplete")


def research_assembly_profile(market: str) -> ResearchAssemblyProfile:
    normalized = market.strip().upper()
    feature = price_volume_feature_spec(normalized)
    return ResearchAssemblyProfile(
        market=normalized,
        feature_schema_hash=feature.schema_hash,
        feature_names=PRICE_VOLUME_FEATURE_NAMES,
        availability_modes=PRICE_VOLUME_AVAILABILITY_MODES,
        scheduling_hint_reason=RESEARCH_SCHEDULING_HINT_REASON,
        label_version=(
            f"{normalized.lower()}-research-unadjusted-open-close-5d-v1"
        ),
    )


TWSE_RESEARCH_ASSEMBLY_PROFILE = research_assembly_profile("TWSE")
TPEX_RESEARCH_ASSEMBLY_PROFILE = research_assembly_profile("TPEX")


__all__ = [
    "ResearchAssemblyProfile",
    "TPEX_RESEARCH_ASSEMBLY_PROFILE",
    "TWSE_RESEARCH_ASSEMBLY_PROFILE",
    "research_assembly_profile",
]
