from datetime import datetime
from decimal import Decimal
import json
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.features.twse_price_volume_schema import (
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
    TWSE_RESEARCH_SCHEDULING_HINT_REASON,
)
from src.pipeline.research_dataset import PreparedResearchDataset
from src.pipeline.twse_research_dataset_assembler import (
    LABEL_VERSION,
    assemble_twse_research_dataset,
)
from src.trading.cost_contracts import TransactionCostConfig
from src.trading.transaction_cost import TransactionCostModel


TAIPEI = ZoneInfo("Asia/Taipei")
SESSIONS = tuple(
    timestamp.date() for timestamp in pd.bdate_range("2024-01-02", periods=8)
)


def _bars() -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for index, session in enumerate(SESSIONS):
        output.append(
            {
                "symbol": "2330",
                "market": "TWSE",
                "trade_date": session,
                "open_price": 100 + index,
                "close_price": 100 + index,
            }
        )
    output[1]["open_price"] = 100
    output[5]["close_price"] = 110
    return output


def _benchmark() -> list[dict[str, object]]:
    return [
        {"session_date": session, "total_return_index": 1_000 + index * 2}
        for index, session in enumerate(SESSIONS)
    ]


def _feature_row(
    *,
    available_at: datetime | None = None,
    observed_available_at: datetime | None = None,
    availability_mode: str = "STRICT_CANONICAL",
) -> dict[str, object]:
    decision_date = SESSIONS[0]
    values = {
        "raw_close_return_1d": 0.01,
        "raw_close_return_2d": 0.02,
        "raw_close_return_3d": 0.03,
        "raw_close_return_5d": 0.04,
        "raw_close_return_10d": 0.05,
        "raw_close_return_20d": 0.06,
        "raw_close_return_60d": 0.07,
        "overnight_gap_1d": 0.001,
        "intraday_return_1d": 0.002,
        "atr_14": 0.02,
        "realized_volatility_20": 0.04,
        "downside_volatility_20": 0.02,
        "maximum_drawdown_20": -0.08,
        "turnover_ntd_mean_20": 100_000_000,
        "volume_anomaly_20": 0.1,
        "amihud_illiquidity_20": 0.000001,
        "adv20_ntd": 100_000_000,
    }
    effective = available_at or datetime(2024, 1, 2, 16, tzinfo=TAIPEI)
    observed = observed_available_at or effective
    limitations = (
        (TWSE_RESEARCH_SCHEDULING_HINT_REASON,)
        if availability_mode == "RESEARCH_SCHEDULING_HINT"
        else ()
    )
    return {
        "symbol": "2330",
        "market": "TWSE",
        "decision_date": decision_date,
        "decision_at": datetime(2024, 1, 2, 17, tzinfo=TAIPEI),
        "latest_available_at": effective,
        "latest_observed_available_at": observed,
        "availability_mode": availability_mode,
        "point_in_time_audit_pass": availability_mode == "STRICT_CANONICAL"
        and observed <= datetime(2024, 1, 2, 17, tzinfo=TAIPEI),
        "research_limitation_reason_codes": limitations,
        "hard_fail": False,
        "hard_fail_reason_codes": (),
        "feature_schema_hash": TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
        **values,
    }


def _cost_model() -> TransactionCostModel:
    return TransactionCostModel(
        TransactionCostConfig(
            commission_rate=Decimal("0"),
            minimum_fee=Decimal("0"),
            sell_tax_rate=Decimal("0"),
            market_impact_parameter=Decimal("0"),
            version="test-cost-v1",
        )
    )


def _assemble(**overrides: object):
    arguments: dict[str, object] = {
        "raw_bars": _bars(),
        "feature_rows": [_feature_row()],
        "benchmark_sessions": _benchmark(),
        "benchmark_id": "TWSE_TOTAL_RETURN_INDEX",
        "benchmark_version": "twse-tri-test-v1",
        "dataset_snapshot_id": "snapshot-test-001",
        "source_hash": "a" * 64,
        "transaction_cost_model": _cost_model(),
    }
    arguments.update(overrides)
    return assemble_twse_research_dataset(**arguments)


def test_assembles_t_plus_one_open_to_fifth_session_close_and_net_alpha() -> None:
    result = _assemble()

    assert result.audit.system_status == "RESEARCH_ONLY"
    assert result.audit.prepared_row_count == 1
    assert result.audit.excluded_row_count == 0
    assert "FORMAL_LABEL_FACTORY_NOT_USED" in result.audit.audit_reason_codes
    row = result.prepared_rows.iloc[0]
    assert row["entry_at"].tz_convert(TAIPEI).date() == SESSIONS[1]
    assert row["entry_at"].tz_convert(TAIPEI).hour == 9
    assert row["exit_at"].tz_convert(TAIPEI).date() == SESSIONS[5]
    assert row["exit_at"].tz_convert(TAIPEI).hour == 13
    assert row["gross_return"] == pytest.approx(0.10)
    assert row["net_return"] == pytest.approx(
        row["gross_return"] - row["round_trip_cost_rate"]
    )
    assert row["benchmark_return"] == pytest.approx(1_010 / 1_000 - 1)
    assert row["net_alpha"] == pytest.approx(
        row["net_return"] - row["benchmark_return"]
    )
    assert row["direction"] == "UP"
    assert row["system_status"] == "RESEARCH_ONLY"
    assert row["label_version"] == LABEL_VERSION
    assert row["dataset_snapshot_id"] == "snapshot-test-001"
    assert row["feature_schema_hash"] == TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH
    assert row["reason_codes"]
    PreparedResearchDataset.from_frame(result.prepared_rows)


def test_accepts_archive_benchmark_and_json_limitation_contracts() -> None:
    feature = _feature_row(availability_mode="RESEARCH_SCHEDULING_HINT")
    feature["research_limitation_reason_codes"] = json.dumps(
        [TWSE_RESEARCH_SCHEDULING_HINT_REASON]
    )
    benchmark = [
        {"trade_date": session, "price": 1_000 + index * 2}
        for index, session in enumerate(SESSIONS)
    ]

    result = _assemble(feature_rows=[feature], benchmark_sessions=benchmark)

    assert result.audit.prepared_row_count == 1
    assert result.audit.scheduling_hint_row_count == 1
    row = result.prepared_rows.iloc[0]
    assert row["benchmark_return"] == pytest.approx(1_010 / 1_000 - 1)


@pytest.mark.parametrize(
    ("interval_name", "reason_code"),
    [
        ("corporate_action_intervals", "KNOWN_CORPORATE_ACTION_WINDOW"),
        ("suspension_intervals", "KNOWN_SUSPENSION_WINDOW"),
    ],
)
def test_known_action_or_suspension_window_is_excluded(
    interval_name: str, reason_code: str
) -> None:
    evidence = [
        {
            "symbol": "2330",
            "start_date": SESSIONS[3],
            "end_date": SESSIONS[3],
        }
    ]
    result = _assemble(**{interval_name: evidence})

    assert result.prepared_rows.empty
    assert result.audit.excluded_row_count == 1
    assert reason_code in result.exclusions[0].reason_codes
    assert result.audit.reason_counts[reason_code] == 1


def test_missing_intermediate_holding_session_bar_is_not_silently_skipped() -> None:
    bars = [row for row in _bars() if row["trade_date"] != SESSIONS[3]]
    result = _assemble(raw_bars=bars)

    assert result.prepared_rows.empty
    assert "MISSING_HOLDING_SESSION_BAR" in result.exclusions[0].reason_codes


def test_future_first_observation_requires_explicit_research_scheduling_hint() -> None:
    future_available = datetime(2026, 7, 19, 8, tzinfo=TAIPEI)
    without_hint = _assemble(
        feature_rows=[
            _feature_row(
                available_at=future_available,
                observed_available_at=future_available,
            )
        ]
    )

    assert without_hint.prepared_rows.empty
    assert "POINT_IN_TIME_VIOLATION" in without_hint.exclusions[0].reason_codes

    with_hint = _assemble(
        feature_rows=[
            _feature_row(
                available_at=datetime(2024, 1, 2, 16, tzinfo=TAIPEI),
                observed_available_at=future_available,
                availability_mode="RESEARCH_SCHEDULING_HINT",
            )
        ]
    )
    assert len(with_hint.prepared_rows) == 1
    row = with_hint.prepared_rows.iloc[0]
    assert row["availability_basis"] == "SCHEDULING_HINT"
    assert row["source_latest_available_at"] > row["decision_at"]
    assert "SCHEDULING_HINT_NOT_OFFICIAL_PIT" in row["reason_codes"]
    assert with_hint.audit.scheduling_hint_row_count == 1
    assert "SCHEDULING_HINT_NOT_OFFICIAL_PIT" in with_hint.audit.audit_reason_codes


def test_missing_schema_hash_and_incomplete_benchmark_fail_closed() -> None:
    feature = _feature_row()
    feature["feature_schema_hash"] = "wrong"
    benchmark = _benchmark()
    benchmark[5]["total_return_index"] = None
    result = _assemble(feature_rows=[feature], benchmark_sessions=benchmark)

    assert result.prepared_rows.empty
    reasons = result.exclusions[0].reason_codes
    assert "FEATURE_SCHEMA_HASH_MISMATCH" in reasons
    assert "BENCHMARK_WINDOW_MISSING" in reasons


def test_complete_known_evidence_still_cannot_promote_unadjusted_research_labels() -> (
    None
):
    result = _assemble(
        corporate_action_history_verified=True,
        security_state_history_verified=True,
        feature_point_in_time_verified=True,
    )

    assert result.audit.system_status == "RESEARCH_ONLY"
    assert result.audit.usage_scope == "MODEL_RESEARCH_ONLY"
    assert result.audit.audit_reason_codes == (
        "UNADJUSTED_PRICE_RESEARCH_ONLY",
        "FORMAL_LABEL_FACTORY_NOT_USED",
        "BENCHMARK_CLOSE_TO_CLOSE_NOT_EXECUTION_PATH_ALIGNED",
    )
