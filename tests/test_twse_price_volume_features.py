from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from math import log, sqrt
from statistics import fmean, median
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.features.twse_price_volume_builder import (
    build_twse_price_volume_features,
)
from src.features.twse_price_volume_schema import (
    TWSE_PRICE_VOLUME_FEATURE_NAMES,
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
)


TAIPEI = ZoneInfo("Asia/Taipei")


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TAIPEI)


def _strict_bars(count: int = 70) -> list[dict[str, object]]:
    start = date(2025, 1, 2)
    rows: list[dict[str, object]] = []
    for index in range(count):
        trade_date = start + timedelta(days=index)
        close = 100.0 + index
        volume = 1_000.0 + index
        rows.append(
            {
                "security_id": 1,
                "listing_period_id": "TWSE:2330:2000-01-01",
                "market": "TWSE",
                "symbol": "2330",
                "asset_type": "COMMON_STOCK",
                "trade_date": trade_date,
                "decision_at": _at(trade_date, 17),
                "available_at": _at(trade_date, 16),
                "available_at_basis": "OFFICIAL_PUBLICATION_AT",
                "open_price": close - 0.5,
                "high_price": close + 1.0,
                "low_price": close - 1.0,
                "close_price": close,
                "trading_volume": volume,
                "trading_value": close * volume,
                "point_in_time_status": "VERIFIED",
                "parse_status": "PARSED",
                "reason_codes": (),
            }
        )
    return rows


def _first_observed_bars() -> list[dict[str, object]]:
    rows = _strict_bars()
    observed_at = datetime(2026, 7, 19, 4, tzinfo=ZoneInfo("UTC"))
    source_reasons = (
        "RAW_POINT_IN_TIME_UNVERIFIED",
        "ROW_POINT_IN_TIME_UNVERIFIED",
        "RAW_AVAILABLE_AT_FIRST_OBSERVED_ONLY",
        "BAR_AVAILABLE_AFTER_DECISION",
    )
    for row in rows:
        row["available_at"] = observed_at
        row["available_at_basis"] = "FIRST_OBSERVED_AT_RETRIEVAL"
        row["point_in_time_status"] = "UNVERIFIED"
        row["reason_codes"] = source_reasons
    return rows


def _last_row(records: object, **kwargs: object):
    result = build_twse_price_volume_features(records, **kwargs)  # type: ignore[arg-type]
    return result, result.rows[-1]


def test_complete_strict_features_are_auditable_and_formula_correct() -> None:
    bars = _strict_bars()
    result, row = _last_row(pd.DataFrame(bars))

    assert result.system_status == "RESEARCH_ONLY"
    assert result.availability_mode == "STRICT_CANONICAL"
    assert row.system_status == "RESEARCH_ONLY"
    assert row.usage_scope == "FEATURE_RESEARCH_ONLY"
    assert row.feature_schema_hash == TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH
    assert tuple(row.feature_values) == TWSE_PRICE_VOLUME_FEATURE_NAMES
    assert len(TWSE_PRICE_VOLUME_FEATURE_NAMES) == 17
    assert "decision_close_price" not in TWSE_PRICE_VOLUME_FEATURE_NAMES
    assert not any("total_return" in name for name in row.feature_values)
    assert row.hard_fail is False
    assert row.point_in_time_audit_pass is True
    assert row.research_limitation_reason_codes == ()

    closes = [float(record["close_price"]) for record in bars]
    assert row.decision_close_price == closes[-1]
    volumes = [float(record["trading_volume"]) for record in bars]
    turnovers = [float(record["trading_value"]) for record in bars]
    for lag in (1, 2, 3, 5, 10, 20, 60):
        assert row.feature_values[f"raw_close_return_{lag}d"] == pytest.approx(
            closes[-1] / closes[-1 - lag] - 1.0
        )
    assert row.feature_values["overnight_gap_1d"] == pytest.approx(
        float(bars[-1]["open_price"]) / closes[-2] - 1.0
    )
    assert row.feature_values["intraday_return_1d"] == pytest.approx(
        closes[-1] / float(bars[-1]["open_price"]) - 1.0
    )
    assert row.feature_values["atr_14"] == pytest.approx(2.0 / closes[-1])
    log_returns = [
        log(current / previous)
        for previous, current in zip(closes[-21:-1], closes[-20:], strict=True)
    ]
    assert row.feature_values["realized_volatility_20"] == pytest.approx(
        sqrt(sum(value**2 for value in log_returns))
    )
    assert row.feature_values["downside_volatility_20"] == 0.0
    assert row.feature_values["maximum_drawdown_20"] == 0.0
    assert row.feature_values["adv20_ntd"] == pytest.approx(fmean(turnovers[-20:]))
    assert row.feature_values["turnover_ntd_mean_20"] == pytest.approx(
        fmean(turnovers[-20:])
    )
    assert row.feature_values["volume_anomaly_20"] == pytest.approx(
        volumes[-1] / median(volumes[-20:]) - 1.0
    )
    expected_amihud = fmean(
        abs(current / previous - 1.0) / turnover
        for previous, current, turnover in zip(
            closes[-21:-1], closes[-20:], turnovers[-20:], strict=True
        )
    )
    assert row.feature_values["amihud_illiquidity_20"] == pytest.approx(expected_amihud)
    assert all(
        audit.available_at <= row.decision_at
        and audit.available_at == audit.observed_available_at
        for audit in row.feature_audits.values()
    )

    with pytest.raises(ValueError, match="decision_close_price"):
        _ = replace(row, decision_close_price=0.0)


def test_strict_mode_does_not_downgrade_first_observed_evidence() -> None:
    _, row = _last_row(_first_observed_bars())

    assert row.hard_fail is True
    assert row.point_in_time_audit_pass is False
    assert set(row.feature_values.values()) == {None}
    assert "RAW_POINT_IN_TIME_UNVERIFIED" in row.hard_fail_reason_codes
    assert "POINT_IN_TIME_VIOLATION" in row.hard_fail_reason_codes
    assert row.research_limitation_reason_codes == ()


def test_explicit_hint_releases_research_values_but_preserves_limitations() -> None:
    bars = _first_observed_bars()
    _, row = _last_row(bars, availability_mode="RESEARCH_SCHEDULING_HINT")

    assert row.hard_fail is False
    assert row.point_in_time_audit_pass is False
    assert not row.missing_features
    assert "RESEARCH_SCHEDULING_HINT" in row.research_limitation_reason_codes
    assert "RAW_POINT_IN_TIME_UNVERIFIED" in row.research_limitation_reason_codes
    assert "BAR_AVAILABLE_AFTER_DECISION" in row.research_limitation_reason_codes
    assert row.hard_fail_reason_codes == ()
    assert row.latest_available_at == _at(row.decision_date, 16)
    assert row.latest_observed_available_at == bars[-1]["available_at"]
    audit = row.feature_audits["raw_close_return_60d"]
    assert audit.source_available_at_bases == ("FIRST_OBSERVED_AT_RETRIEVAL",)
    assert audit.observed_available_at == bars[-1]["available_at"]
    assert audit.available_at == _at(row.decision_date, 16)


def test_hint_never_downgrades_a_non_allowlisted_source_failure() -> None:
    bars = _first_observed_bars()
    for bar in bars:
        bar["reason_codes"] = (
            *bar["reason_codes"],  # type: ignore[misc]
            "PROVIDER_OHLC_QUALITY_FAILURE",
        )
    _, row = _last_row(bars, availability_mode="RESEARCH_SCHEDULING_HINT")

    assert row.hard_fail is True
    assert set(row.feature_values.values()) == {None}
    assert "PROVIDER_OHLC_QUALITY_FAILURE" in row.hard_fail_reason_codes
    assert "RESEARCH_SCHEDULING_HINT" in row.research_limitation_reason_codes


def test_research_hint_after_decision_cutoff_is_a_hard_pit_failure() -> None:
    bars = _first_observed_bars()
    for bar in bars:
        bar["decision_at"] = _at(bar["trade_date"], 15, 59)  # type: ignore[arg-type]
    _, row = _last_row(bars, availability_mode="RESEARCH_SCHEDULING_HINT")

    assert row.hard_fail is True
    assert "POINT_IN_TIME_VIOLATION" in row.hard_fail_reason_codes
    assert set(row.feature_values.values()) == {None}


def test_future_input_only_blocks_features_whose_window_uses_it() -> None:
    bars = _strict_bars()
    bars[9]["available_at"] = datetime(2030, 1, 1, tzinfo=ZoneInfo("UTC"))
    _, row = _last_row(bars)

    assert row.feature_values["raw_close_return_60d"] is None
    assert (
        "POINT_IN_TIME_VIOLATION"
        in row.feature_audits["raw_close_return_60d"].reason_codes
    )
    assert row.feature_values["raw_close_return_20d"] is not None
    assert row.feature_values["atr_14"] is not None
