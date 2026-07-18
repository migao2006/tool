from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from src.labels.label_factory import (
    CorporateActionCoverage,
    DirectionLabel,
    ExecutablePrice,
    LabelDataError,
    LabelFactory,
    NoTradeBandConfig,
    TradingCalendar,
)
from src.trading.cost_contracts import TransactionCostConfig
from src.trading.transaction_cost import TransactionCostModel


TAIPEI = ZoneInfo("Asia/Taipei")


def _calendar() -> TradingCalendar:
    start = date(2026, 7, 1)
    sessions = [start + timedelta(days=offset) for offset in (0, 1, 2, 5, 6, 7, 8, 9)]
    return TradingCalendar(sessions)


def _coverage(*, end_date: date = date(2026, 7, 8)) -> CorporateActionCoverage:
    return CorporateActionCoverage(
        start_date=date(2026, 7, 2),
        end_date=end_date,
        source_version="test-actions-v1",
    )


def _external_cost_inputs() -> dict[str, Decimal | str]:
    return {
        "round_trip_cost_rate": Decimal("0.005"),
        "cost_profile_version": "test-cost-v1",
    }


def test_factory_reuses_transaction_cost_and_builds_all_label_targets() -> None:
    cost_model = TransactionCostModel(
        TransactionCostConfig(
            commission_rate=Decimal("0"),
            minimum_fee=Decimal("0"),
            sell_tax_rate=Decimal("0.003"),
            market_impact_parameter=Decimal("0"),
            version="test-cost-v2",
        )
    )
    factory = LabelFactory(_calendar(), transaction_cost_model=cost_model)
    result = factory.create(
        symbol="2330",
        decision_at=datetime(2026, 7, 1, 17, tzinfo=TAIPEI),
        entry_open=ExecutablePrice(
            date(2026, 7, 2), 100, bid=Decimal("100"), ask=Decimal("100")
        ),
        exit_close=ExecutablePrice(
            date(2026, 7, 8), 110, bid=Decimal("110"), ask=Decimal("110")
        ),
        benchmark_return=Decimal("0.01"),
        benchmark_id="TAIEX",
        benchmark_version="2026-v1",
        quantity=Decimal("1000"),
        adv20_ntd=Decimal("100000000"),
        corporate_action_coverage=_coverage(),
        trailing_volatility=0.02,
        no_trade_band_config=NoTradeBandConfig(
            horizon=5,
            min_edge_h=0.01,
            k_h=0.5,
            version="test-band-v1",
        ),
    )

    assert result.valid is True
    assert result.gross_return == Decimal("0.1")
    assert result.round_trip_cost_rate == Decimal("0.0033")
    assert result.net_return == Decimal("0.0967")
    assert result.benchmark_alpha == Decimal("0.0867")
    assert result.direction is DirectionLabel.UP
    assert result.no_trade_band is not None
    assert result.no_trade_band_version == "test-band-v1"
    assert result.cost_profile_version == "test-cost-v2:base_cost"


def test_cost_model_rejects_missing_liquidity_instead_of_assuming_capacity() -> None:
    factory = LabelFactory(_calendar(), TransactionCostModel())
    result = factory.create(
        symbol="2330",
        decision_at=datetime(2026, 7, 1, 17, tzinfo=TAIPEI),
        entry_open=ExecutablePrice(date(2026, 7, 2), 100),
        exit_close=ExecutablePrice(date(2026, 7, 8), 101),
        benchmark_return=0,
        benchmark_id="TAIEX",
        benchmark_version="v1",
        corporate_action_coverage=_coverage(),
    )

    assert result.valid is False
    assert result.net_return is None
    assert "ADV20_MISSING" in result.reason_codes


def test_factory_rejects_missing_or_unverified_required_data() -> None:
    factory = LabelFactory(_calendar())
    common = {
        "symbol": "2330",
        "decision_at": datetime(2026, 7, 1, 17, tzinfo=TAIPEI),
        "entry_open": ExecutablePrice(date(2026, 7, 2), 100),
        "exit_close": ExecutablePrice(date(2026, 7, 8), 101),
        "benchmark_return": Decimal("0"),
        "benchmark_id": "TAIEX",
        "benchmark_version": "v1",
        **_external_cost_inputs(),
    }

    with pytest.raises(LabelDataError, match="entry_open is required"):
        factory.create(
            **(common | {"entry_open": None}),
            corporate_action_coverage=_coverage(),
        )
    with pytest.raises(LabelDataError, match="corporate_action_coverage"):
        factory.create(**common)
    with pytest.raises(LabelDataError, match="complete"):
        factory.create(
            **common, corporate_action_coverage=_coverage(end_date=date(2026, 7, 7))
        )
    with pytest.raises(LabelDataError, match="executable price is required"):
        ExecutablePrice(date(2026, 7, 2), None)


def test_factory_rejects_non_session_decision_and_wrong_execution_session() -> None:
    factory = LabelFactory(_calendar())
    common = {
        "symbol": "2330",
        "benchmark_return": Decimal("0"),
        "benchmark_id": "TAIEX",
        "benchmark_version": "v1",
        "corporate_action_coverage": _coverage(),
        **_external_cost_inputs(),
    }

    with pytest.raises(ValueError, match="decision_date must be an exchange session"):
        factory.create(
            **common,
            decision_at=datetime(2026, 7, 4, 17, tzinfo=TAIPEI),
            entry_open=ExecutablePrice(date(2026, 7, 5), 100),
            exit_close=ExecutablePrice(date(2026, 7, 10), 101),
        )
    with pytest.raises(ValueError, match=r"t\+1 exchange-session open"):
        factory.create(
            **common,
            decision_at=datetime(2026, 7, 1, 17, tzinfo=TAIPEI),
            entry_open=ExecutablePrice(date(2026, 7, 3), 100),
            exit_close=ExecutablePrice(date(2026, 7, 8), 101),
        )
