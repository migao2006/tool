from __future__ import annotations

import pytest

from src.data.ingestion.historical_supplemental_backfill_settings import (
    HistoricalSupplementalBackfillSettings,
)


def test_free_tier_defaults_exclude_adjusted_bars() -> None:
    settings = HistoricalSupplementalBackfillSettings.from_env({})

    assert settings.allowed_datasets == (
        "institutional_flows",
        "margin_short",
    )


def test_paid_tier_can_explicitly_enable_adjusted_bars() -> None:
    settings = HistoricalSupplementalBackfillSettings.from_env(
        {
            "HISTORICAL_SUPPLEMENTAL_ALLOWED_DATASETS": (
                "adjusted_bars,institutional_flows,margin_short"
            )
        }
    )

    assert settings.allowed_datasets[0] == "adjusted_bars"


@pytest.mark.parametrize(
    "value",
    ["", "adjusted_bars,adjusted_bars", "monthly_revenue"],
)
def test_invalid_dataset_policy_fails_closed(value: str) -> None:
    with pytest.raises(ValueError):
        _ = HistoricalSupplementalBackfillSettings.from_env(
            {"HISTORICAL_SUPPLEMENTAL_ALLOWED_DATASETS": value}
        )
