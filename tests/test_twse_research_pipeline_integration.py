from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from src.features.twse_price_volume_builder import (
    build_twse_price_volume_features,
)
from src.pipeline.research_dataset import PreparedResearchDataset
from src.pipeline.twse_research_dataset_assembler import (
    assemble_twse_research_dataset,
)


TAIPEI = ZoneInfo("Asia/Taipei")


def test_raw_bars_flow_through_features_labels_and_training_contract() -> None:
    sessions = tuple(
        timestamp.date() for timestamp in pd.bdate_range("2024-01-02", periods=75)
    )
    observed_at = datetime(2026, 7, 19, 8, tzinfo=TAIPEI)
    canonical: list[dict[str, object]] = []
    raw_bars: list[dict[str, object]] = []
    benchmark: list[dict[str, object]] = []
    for index, session in enumerate(sessions):
        price = 100 + index * 0.1
        raw_bars.append(
            {
                "symbol": "2330",
                "market": "TWSE",
                "trade_date": session,
                "open_price": price,
                "close_price": price + 0.05,
            }
        )
        canonical.append(
            {
                "security_id": 1,
                "listing_period_id": "research-current:1:2330",
                "market": "TWSE",
                "asset_type": "COMMON_STOCK",
                "symbol": "2330",
                "trade_date": session,
                "decision_at": datetime.combine(
                    session,
                    datetime.min.time().replace(hour=18),
                    tzinfo=TAIPEI,
                ),
                "available_at": observed_at,
                "raw_available_at": observed_at,
                "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
                "raw_available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
                "point_in_time_status": "UNVERIFIED",
                "parse_status": "PARSED",
                "open_price": price,
                "high_price": price + 0.2,
                "low_price": price - 0.2,
                "close_price": price + 0.05,
                "trading_volume": 1_000_000 + index,
                "trading_value": 100_000_000 + index * 10_000,
                "reason_codes": (
                    "RAW_POINT_IN_TIME_UNVERIFIED",
                    "RAW_AVAILABLE_AT_FIRST_OBSERVED_ONLY",
                ),
            }
        )
        benchmark.append(
            {
                "session_date": session,
                "total_return_index": 1_000 + index,
            }
        )

    feature_result = build_twse_price_volume_features(
        canonical,
        trading_sessions=sessions,
        availability_mode="RESEARCH_SCHEDULING_HINT",
    )
    assembly = assemble_twse_research_dataset(
        raw_bars=raw_bars,
        feature_rows=feature_result,
        benchmark_sessions=benchmark,
        benchmark_id="TWSE_TOTAL_RETURN_INDEX",
        benchmark_version="integration-test-v1",
        dataset_snapshot_id="integration-snapshot-v1",
        source_hash="a" * 64,
    )

    assert feature_result.system_status == "RESEARCH_ONLY"
    assert feature_result.hard_fail_count > 0
    assert not assembly.prepared_rows.empty
    assert assembly.audit.scheduling_hint_row_count > 0
    assert assembly.audit.system_status == "RESEARCH_ONLY"
    prepared = PreparedResearchDataset.from_frame(assembly.prepared_rows)
    assert prepared.frame["system_status"].eq("RESEARCH_ONLY").all()
    assert prepared.frame["availability_basis"].eq("SCHEDULING_HINT").all()
