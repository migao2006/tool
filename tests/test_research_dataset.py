from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from src.pipeline.research_dataset import (
    PreparedResearchDataset,
    ResearchDatasetError,
    TWSE_PRICE_RESEARCH_FEATURES,
)
from src.features.twse_price_volume_schema import (
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
)


UTC = timezone.utc


def _frame() -> pd.DataFrame:
    decision_at = datetime(2026, 7, 17, 6, 30, tzinfo=UTC)
    row: dict[str, object] = {
        "symbol": "2330",
        "market": "TWSE",
        "horizon": 5,
        "decision_date": date(2026, 7, 17),
        "decision_at": decision_at,
        "available_at": decision_at,
        "source_latest_available_at": decision_at,
        "availability_basis": "SOURCE_AVAILABLE_AT",
        "entry_at": decision_at + timedelta(days=1),
        "exit_at": decision_at + timedelta(days=7),
        "gross_return": 0.03,
        "net_return": 0.024,
        "net_alpha": 0.012,
        "round_trip_cost_rate": 0.006,
        "direction": "UP",
        "data_quality_status": "WARN",
        "system_status": "RESEARCH_ONLY",
        "usage_scope": "MODEL_RESEARCH_ONLY",
        "reason_codes": ("UNADJUSTED_PRICE_RESEARCH_ONLY",),
        "feature_schema_hash": TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
        "label_version": "label-v1",
        "benchmark_id": "TAIEX",
        "benchmark_version": "benchmark-v1",
        "cost_profile_version": "cost-v1",
        "dataset_snapshot_id": "snapshot-v1",
        "source_hash": "a" * 64,
    }
    row.update({name: 0.01 for name in TWSE_PRICE_RESEARCH_FEATURES})
    return pd.DataFrame([row])


def test_prepared_research_dataset_accepts_audited_twse_rows() -> None:
    dataset = PreparedResearchDataset.from_frame(_frame())
    observation = dataset.observations()[0]

    assert dataset.feature_names == TWSE_PRICE_RESEARCH_FEATURES
    assert dataset.latest_training_date == date(2026, 7, 17)
    assert observation.sample_id == "2330:2026-07-17"
    assert observation.decision_date == date(2026, 7, 17)
    assert observation.entry_at == datetime(2026, 7, 18, 6, 30, tzinfo=UTC)
    assert observation.exit_at == datetime(2026, 7, 24, 6, 30, tzinfo=UTC)


def test_prepared_research_dataset_rejects_future_features() -> None:
    frame = _frame()
    frame.loc[0, "available_at"] = frame.loc[0, "decision_at"] + timedelta(seconds=1)

    with pytest.raises(ResearchDatasetError, match="available_at"):
        PreparedResearchDataset.from_frame(frame)


def test_prepared_research_dataset_preserves_research_scheduling_hint() -> None:
    frame = _frame()
    frame.loc[0, "source_latest_available_at"] = frame.loc[
        0, "decision_at"
    ] + timedelta(days=30)
    frame.loc[0, "availability_basis"] = "SCHEDULING_HINT"
    frame.at[0, "reason_codes"] = (
        "UNADJUSTED_PRICE_RESEARCH_ONLY",
        "SCHEDULING_HINT_NOT_OFFICIAL_PIT",
    )

    dataset = PreparedResearchDataset.from_frame(frame)

    assert dataset.frame.loc[0, "availability_basis"] == "SCHEDULING_HINT"


def test_prepared_research_dataset_rejects_unmarked_scheduling_hint() -> None:
    frame = _frame()
    frame.loc[0, "availability_basis"] = "SCHEDULING_HINT"

    with pytest.raises(ResearchDatasetError, match="point-in-time limitation"):
        PreparedResearchDataset.from_frame(frame)


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("market", "TPEX", "TWSE"),
        ("horizon", 3, "horizon=5"),
        ("data_quality_status", "HARD_FAIL", "HARD_FAIL"),
    ],
)
def test_prepared_research_dataset_rejects_out_of_scope_rows(
    column: str, value: object, message: str
) -> None:
    frame = _frame()
    frame.loc[0, column] = value

    with pytest.raises(ResearchDatasetError, match=message):
        PreparedResearchDataset.from_frame(frame)


def test_prepared_research_dataset_rejects_duplicate_symbol_date() -> None:
    frame = pd.concat([_frame(), _frame()], ignore_index=True)

    with pytest.raises(ResearchDatasetError, match="unique"):
        PreparedResearchDataset.from_frame(frame)


def test_prepared_research_dataset_rejects_infinite_values() -> None:
    frame = _frame()
    frame.loc[0, "raw_close_return_5d"] = float("inf")

    with pytest.raises(ResearchDatasetError, match="finite"):
        PreparedResearchDataset.from_frame(frame)
