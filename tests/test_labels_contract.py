from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from src.labels.label_factory import (
    CorporateAction,
    CorporateActionCoverage,
    ExecutablePrice,
    LabelFactory,
    LookAheadError,
    TradingCalendar,
)


TAIPEI = ZoneInfo("Asia/Taipei")


def _sessions() -> list[date]:
    start = date(2026, 7, 1)
    return [start + timedelta(days=offset) for offset in (0, 1, 2, 5, 6, 7, 8, 9)]


def _coverage() -> CorporateActionCoverage:
    return CorporateActionCoverage(
        start_date=date(2026, 7, 2),
        end_date=date(2026, 7, 8),
        source_version="test-actions-v1",
    )


def test_five_session_label_enters_next_open_and_exits_fifth_close() -> None:
    calendar = TradingCalendar(_sessions())
    window = calendar.label_window(date(2026, 7, 1), horizon=5)

    assert window.entry_date == date(2026, 7, 2)
    assert window.exit_date == date(2026, 7, 8)
    assert window.horizon == 5


def test_non_released_horizon_is_not_silently_used_in_production() -> None:
    calendar = TradingCalendar(_sessions())

    with pytest.raises(NotImplementedError):
        calendar.label_window(date(2026, 7, 1), horizon=3)

    research_window = calendar.label_window(date(2026, 7, 1), horizon=3, research=True)
    assert research_window.exit_date == date(2026, 7, 6)


def test_label_rejects_feature_released_after_decision() -> None:
    factory = LabelFactory(TradingCalendar(_sessions()))
    decision_at = datetime(2026, 7, 1, 17, tzinfo=TAIPEI)

    with pytest.raises(LookAheadError, match="future_feature"):
        factory.create(
            symbol="2330",
            decision_at=decision_at,
            entry_open=ExecutablePrice(date(2026, 7, 2), Decimal("100")),
            exit_close=ExecutablePrice(date(2026, 7, 8), Decimal("101")),
            benchmark_return=Decimal("0"),
            benchmark_id="TAIEX",
            benchmark_version="v1",
            round_trip_cost_rate=Decimal("0.005"),
            cost_profile_version="test-cost-v1",
            feature_available_ats={
                "future_feature": decision_at + timedelta(seconds=1)
            },
            corporate_action_coverage=_coverage(),
        )


def test_total_return_includes_entitled_cash_and_split_then_subtracts_cost() -> None:
    factory = LabelFactory(TradingCalendar(_sessions()))
    decision_at = datetime(2026, 7, 1, 17, tzinfo=TAIPEI)
    actions = (
        CorporateAction(
            action_id="cash",
            ex_date=date(2026, 7, 6),
            payable_date=date(2026, 7, 20),
            cash_per_share=Decimal("2"),
        ),
        CorporateAction(
            action_id="split",
            ex_date=date(2026, 7, 7),
            share_multiplier=Decimal("2"),
        ),
    )

    result = factory.create(
        symbol="2330",
        decision_at=decision_at,
        entry_open=ExecutablePrice(date(2026, 7, 2), Decimal("100")),
        exit_close=ExecutablePrice(date(2026, 7, 8), Decimal("54")),
        benchmark_return=Decimal("0.01"),
        benchmark_id="TAIEX",
        benchmark_version="2026-v1",
        round_trip_cost_rate=Decimal("0.005"),
        cost_profile_version="test-cost-v1",
        feature_available_ats={"close": decision_at},
        corporate_actions=actions,
        corporate_action_coverage=_coverage(),
    )

    assert result.valid is True
    assert result.gross_return == Decimal("0.10")  # (2 * 54 + 2) / 100 - 1
    assert result.net_return == Decimal("0.095")
    assert result.excess_return == Decimal("0.085")
    assert result.applied_corporate_actions == ("cash", "split")


def test_buying_at_ex_date_open_does_not_receive_the_entitlement() -> None:
    factory = LabelFactory(TradingCalendar(_sessions()))
    result = factory.create(
        symbol="2330",
        decision_at=datetime(2026, 7, 1, 17, tzinfo=TAIPEI),
        entry_open=ExecutablePrice(date(2026, 7, 2), Decimal("100")),
        exit_close=ExecutablePrice(date(2026, 7, 8), Decimal("100")),
        benchmark_return=Decimal("0"),
        benchmark_id="TAIEX",
        benchmark_version="v1",
        round_trip_cost_rate=Decimal("0"),
        cost_profile_version="test-cost-v1",
        corporate_actions=(
            CorporateAction(
                action_id="ex-date-cash",
                ex_date=date(2026, 7, 2),
                payable_date=date(2026, 7, 20),
                cash_per_share=Decimal("10"),
            ),
        ),
        corporate_action_coverage=_coverage(),
    )

    assert result.gross_return == Decimal("0")
    assert result.applied_corporate_actions == ()


def test_same_ex_date_cash_and_split_use_pre_action_shares_regardless_of_order() -> (
    None
):
    factory = LabelFactory(TradingCalendar(_sessions()))
    cash = CorporateAction(
        action_id="cash",
        ex_date=date(2026, 7, 6),
        cash_per_share=Decimal("2"),
    )
    split = CorporateAction(
        action_id="split",
        ex_date=date(2026, 7, 6),
        share_multiplier=Decimal("2"),
    )

    def create(actions: tuple[CorporateAction, ...]):
        return factory.create(
            symbol="2330",
            decision_at=datetime(2026, 7, 1, 17, tzinfo=TAIPEI),
            entry_open=ExecutablePrice(date(2026, 7, 2), Decimal("100")),
            exit_close=ExecutablePrice(date(2026, 7, 8), Decimal("54")),
            benchmark_return=Decimal("0"),
            benchmark_id="TAIEX",
            benchmark_version="v1",
            round_trip_cost_rate=Decimal("0"),
            cost_profile_version="test-cost-v1",
            corporate_actions=actions,
            corporate_action_coverage=_coverage(),
        )

    assert create((cash, split)).gross_return == Decimal("0.10")
    assert create((split, cash)).gross_return == Decimal("0.10")


def test_daily_limit_without_confirmed_counterparty_is_not_assumed_filled() -> None:
    factory = LabelFactory(TradingCalendar(_sessions()))
    result = factory.create(
        symbol="1234",
        decision_at=datetime(2026, 7, 1, 17, tzinfo=TAIPEI),
        entry_open=ExecutablePrice(
            date(2026, 7, 2),
            Decimal("20"),
            price_limit_state="LIMIT_UP",
            counterparty_volume_confirmed=None,
        ),
        exit_close=ExecutablePrice(date(2026, 7, 8), Decimal("21")),
        benchmark_return=Decimal("0"),
        benchmark_id="TAIEX",
        benchmark_version="v1",
        round_trip_cost_rate=Decimal("0.005"),
        cost_profile_version="test-cost-v1",
        corporate_action_coverage=_coverage(),
    )

    assert result.valid is False
    assert result.gross_return is None
    assert "BUY_LIMIT_FILL_UNCONFIRMED" in result.reason_codes
