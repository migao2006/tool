from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.data.security_master import AssetType, Market, SecurityRecord, TradingStatus
from src.quality.data_quality import (
    DataQualityConfig,
    DataQualityInput,
    Freshness,
    QualityScope,
    evaluate_data_quality,
)


TAIPEI = ZoneInfo("Asia/Taipei")


def _security(**overrides: object) -> SecurityRecord:
    values = {
        "security_id": 2330,
        "listing_period_id": "TWSE:2330:1994-09-05",
        "symbol": "2330",
        "name": "台積電",
        "market": Market.LISTED,
        "industry": "半導體",
        "asset_type": AssetType.COMMON_STOCK,
        "valid_from": date(1994, 9, 5),
        "available_at": datetime(1994, 9, 5, tzinfo=TAIPEI),
        "first_observed_at": datetime(1994, 9, 5, tzinfo=TAIPEI),
        "available_at_basis": "VERSIONED_SNAPSHOT",
        "point_in_time_status": "VERIFIED",
        "usage_scope": "POINT_IN_TIME_IDENTITY",
        "reason_codes": (),
        "source_id": 1,
        "source_version": "snapshot-v1",
        "source_revision_hash": "a" * 64,
        "trading_status": TradingStatus.ACTIVE,
        "attention_flag": False,
        "disposition_flag": False,
        "altered_trading_method_flag": False,
        "full_delivery_flag": False,
        "periodic_auction_flag": False,
        "suspended_flag": False,
    }
    values.update(overrides)
    if "available_at" in overrides and "first_observed_at" not in overrides:
        values["first_observed_at"] = values["available_at"]
    return SecurityRecord(**values)


def _input(security: SecurityRecord, **overrides: object) -> DataQualityInput:
    decision_at = datetime(2026, 7, 17, 17, tzinfo=TAIPEI)
    values = {
        "decision_at": decision_at,
        "security": security,
        "history_sessions": 1000,
        "adv20_ntd": Decimal("100000000"),
        "estimated_order_notional_ntd": Decimal("500000"),
        "has_corporate_action_data": True,
        "has_executable_entry_price": True,
        "has_executable_exit_price": True,
        "expected_fields": ("close", "volume"),
        "present_fields": ("close", "volume"),
        "critical_fields": ("close", "volume"),
        "source_dates": {"TWSE": date(2026, 7, 17)},
        "latest_available_at": datetime(2026, 7, 17, 16, tzinfo=TAIPEI),
        "horizon": 5,
    }
    values.update(overrides)
    return DataQualityInput(**values)


def test_clean_row_passes_with_traceable_quality_fields() -> None:
    result = evaluate_data_quality(_input(_security()))

    assert result.passed is True
    assert result.hard_fail is False
    assert result.completeness_score == 1.0
    assert result.freshness == Freshness.FRESH
    assert result.source_dates == {"TWSE": date(2026, 7, 17)}


def test_disposition_and_missing_critical_data_hard_fail() -> None:
    result = evaluate_data_quality(
        _input(
            _security(disposition_flag=True),
            present_fields=("close",),
            has_corporate_action_data=False,
        )
    )

    assert result.passed is False
    assert result.completeness_score == 0.5
    assert "DISPOSITION_SECURITY" in result.reason_codes
    assert "CRITICAL_FEATURE_MISSING:volume" in result.reason_codes
    assert "CORPORATE_ACTION_DATA_MISSING" in result.reason_codes


def test_suspended_or_capacity_exceeded_cannot_be_recommended() -> None:
    result = evaluate_data_quality(
        _input(
            _security(trading_status=TradingStatus.SUSPENDED),
            adv20_ntd=Decimal("10000000"),
            estimated_order_notional_ntd=Decimal("500000"),
        ),
        DataQualityConfig(
            minimum_adv20_ntd=Decimal("1000000"), max_adv_participation=Decimal("0.01")
        ),
    )

    assert result.hard_fail is True
    assert "TRADING_SUSPENDED" in result.reason_codes
    assert "CAPACITY_LIMIT_EXCEEDED" in result.reason_codes


def test_attention_is_not_excluded_without_explicit_configuration() -> None:
    data = _input(_security(attention_flag=True))

    assert evaluate_data_quality(data).passed is True
    excluded = evaluate_data_quality(data, DataQualityConfig(exclude_attention=True))
    assert excluded.passed is False
    assert "ATTENTION_SECURITY_EXCLUDED" in excluded.reason_codes


def test_unknown_security_state_is_always_a_hard_fail() -> None:
    result = evaluate_data_quality(
        _input(
            _security(
                trading_status=TradingStatus.UNKNOWN,
                full_delivery_flag=None,
                suspended_flag=None,
            )
        )
    )

    assert result.hard_fail is True
    assert "TRADING_STATUS_UNKNOWN" in result.reason_codes
    assert "FULL_DELIVERY_STATUS_UNKNOWN" in result.reason_codes
    assert "SUSPENSION_STATUS_UNKNOWN" in result.reason_codes


def test_live_decision_does_not_require_future_execution_prices() -> None:
    decision_result = evaluate_data_quality(
        _input(
            _security(),
            has_executable_entry_price=False,
            has_executable_exit_price=False,
        )
    )
    assert decision_result.passed is True

    label_result = evaluate_data_quality(
        _input(
            _security(),
            has_executable_entry_price=False,
            has_executable_exit_price=False,
            scope=QualityScope.LABEL,
        )
    )
    assert label_result.passed is False
    assert "EXECUTABLE_ENTRY_PRICE_MISSING" in label_result.reason_codes
    assert "EXECUTABLE_EXIT_PRICE_MISSING" in label_result.reason_codes


def test_fresh_source_cannot_hide_another_stale_source() -> None:
    result = evaluate_data_quality(
        _input(
            _security(),
            source_available_at={
                "price": datetime(2026, 7, 17, 16, tzinfo=TAIPEI),
                "fundamental": datetime(2026, 7, 1, 16, tzinfo=TAIPEI),
            },
        )
    )
    assert result.passed is False
    assert "STALE_SOURCE_DATA:fundamental" in result.reason_codes
