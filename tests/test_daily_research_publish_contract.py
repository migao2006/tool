from __future__ import annotations

import pytest

from src.pipeline.daily_research_publish_contract import (
    DailyResearchPublishContractError,
    require_daily_research_coverage,
)


def test_daily_research_coverage_accepts_complete_cross_sections() -> None:
    require_daily_research_coverage(
        "twse",
        feature_count=1_068,
        prediction_count=1_068,
    )
    require_daily_research_coverage(
        "TPEX",
        feature_count=864,
        prediction_count=864,
    )


def test_daily_research_coverage_rejects_too_few_features_before_inference() -> None:
    with pytest.raises(DailyResearchPublishContractError) as captured:
        require_daily_research_coverage("TWSE", feature_count=499)

    assert captured.value.reason_code == ("TWSE_DAILY_RESEARCH_FEATURE_COVERAGE_TOO_LOW")


def test_daily_research_coverage_rejects_partial_prediction_publication() -> None:
    with pytest.raises(DailyResearchPublishContractError) as captured:
        require_daily_research_coverage(
            "TPEX",
            feature_count=864,
            prediction_count=863,
        )

    assert captured.value.reason_code == ("TPEX_DAILY_RESEARCH_CROSS_SECTION_COUNT_MISMATCH")
