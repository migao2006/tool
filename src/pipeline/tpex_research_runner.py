"""TPEX research runner using the shared five-day model procedure."""

from __future__ import annotations

from src.features.tpex_price_volume_schema import (
    TPEX_PRICE_VOLUME_FEATURE_NAMES,
    TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
)

from .venue_price_research_runner import (
    VenuePriceResearchRunner,
)
from .venue_research_profile import VenuePriceResearchProfile


TPEX_PRICE_RESEARCH_PROFILE = VenuePriceResearchProfile(
    market="TPEX",
    scope="TPEX_PRICE_ONLY",
    model_version="tpex-price-research-h5-v1",
    feature_schema_hash=TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
    feature_names=TPEX_PRICE_VOLUME_FEATURE_NAMES,
    expected_label_version="tpex-research-unadjusted-open-close-5d-v1",
    expected_benchmark_id="TPEX_PRICE_INDEX",
    primary_reason_code="TPEX_PRICE_ONLY_RESEARCH",
    dataset_invalid_reason_code="TPEX_RESEARCH_DATASET_INVALID",
    artifact_stem="tpex",
    bundle_unavailable_reason_code="TPEX_RESEARCH_MODEL_BUNDLE_NOT_IMPLEMENTED",
    require_prepared_run_provenance=True,
)


class TpexPriceResearchRunner(VenuePriceResearchRunner):
    """Run isolated TPEX evaluation without emitting a TWSE-shaped bundle."""

    def __init__(self) -> None:
        super().__init__(TPEX_PRICE_RESEARCH_PROFILE)


tpex_price_research_runner = TpexPriceResearchRunner()


__all__ = [
    "TPEX_PRICE_RESEARCH_PROFILE",
    "TpexPriceResearchRunner",
    "tpex_price_research_runner",
]
