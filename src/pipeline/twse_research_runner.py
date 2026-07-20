"""TWSE compatibility wrapper around the venue-scoped research runner."""

from __future__ import annotations

from src.features.twse_price_volume_schema import (
    TWSE_PRICE_VOLUME_FEATURE_NAMES,
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
)

from .twse_research_bundle_publisher import publish_last_fold_bundle
from .venue_price_research_runner import (
    VenuePriceResearchRunner,
)
from .venue_research_profile import VenuePriceResearchProfile


TWSE_PRICE_RESEARCH_PROFILE = VenuePriceResearchProfile(
    market="TWSE",
    scope="TWSE_PRICE_ONLY",
    model_version="twse-price-research-h5-v1",
    feature_schema_hash=TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
    feature_names=TWSE_PRICE_VOLUME_FEATURE_NAMES,
    expected_label_version="twse-research-unadjusted-open-close-5d-v1",
    expected_benchmark_id="TWSE_TAIEX_PRICE_INDEX",
    primary_reason_code="TWSE_PRICE_ONLY_RESEARCH",
    dataset_invalid_reason_code="TWSE_RESEARCH_DATASET_INVALID",
    artifact_stem="twse",
)


class TwsePriceResearchRunner(VenuePriceResearchRunner):
    """Keep the public TWSE runner name while sharing model orchestration."""

    def __init__(self) -> None:
        super().__init__(
            TWSE_PRICE_RESEARCH_PROFILE,
            bundle_publisher=publish_last_fold_bundle,
        )


twse_price_research_runner = TwsePriceResearchRunner()


__all__ = [
    "TWSE_PRICE_RESEARCH_PROFILE",
    "TwsePriceResearchRunner",
    "twse_price_research_runner",
]
