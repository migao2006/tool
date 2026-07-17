from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.data.point_in_time_dataset import (
    FeatureObservation,
    PointInTimeDatasetBuilder,
    feature_is_available,
)
from src.data.preprocessing import CrossSectionalMedianImputer, FoldFitScope
from src.data.security_master import (
    AssetType,
    BenchmarkAssignment,
    Market,
    SecurityMaster,
    SecurityRecord,
    TradingStatus,
)


def test_market_aliases_persist_using_exchange_codes() -> None:
    assert Market.LISTED is Market.TWSE
    assert Market.OTC is Market.TPEX
    assert Market.LISTED.value == "TWSE"
    assert Market.OTC.value == "TPEX"


TAIPEI = ZoneInfo("Asia/Taipei")
NEW_YORK = ZoneInfo("America/New_York")


def _master() -> SecurityMaster:
    return SecurityMaster(
        records=(
            SecurityRecord(
                symbol="1111",
                name="歷史公司",
                market=Market.LISTED,
                industry="測試",
                asset_type=AssetType.COMMON_STOCK,
                valid_from=date(2020, 1, 1),
                valid_to=date(2026, 8, 1),
                trading_status=TradingStatus.ACTIVE,
            ),
            SecurityRecord(
                symbol="0050",
                name="ETF",
                market=Market.ETF,
                industry="ETF",
                asset_type=AssetType.ETF,
                valid_from=date(2020, 1, 1),
            ),
        ),
        benchmarks=(
            BenchmarkAssignment(Market.LISTED, "TAIEX", "2026-v1", date(2020, 1, 1)),
            BenchmarkAssignment(Market.OTC, "TPEX", "2026-v1", date(2020, 1, 1)),
            BenchmarkAssignment(Market.ETF, "ETF-SEPARATE", "2026-v1", date(2020, 1, 1)),
        ),
    )


def test_us_same_day_close_is_excluded_before_it_occurs_in_taiwan() -> None:
    decision_at = datetime(2026, 7, 17, 17, tzinfo=TAIPEI)
    same_calendar_day_us_close = datetime(2026, 7, 17, 16, tzinfo=NEW_YORK)
    prior_us_close = datetime(2026, 7, 16, 16, tzinfo=NEW_YORK)

    assert feature_is_available(same_calendar_day_us_close, decision_at) is False
    assert feature_is_available(prior_us_close, decision_at) is True


def test_snapshot_uses_latest_revision_available_at_decision_and_excludes_etf() -> None:
    decision_at = datetime(2026, 7, 17, 17, tzinfo=TAIPEI)
    observations = (
        FeatureObservation("1111", "close", 10, date(2026, 7, 16), datetime(2026, 7, 16, 15, 30, tzinfo=TAIPEI), "TWSE"),
        FeatureObservation("1111", "close", 11, date(2026, 7, 17), datetime(2026, 7, 17, 15, 30, tzinfo=TAIPEI), "TWSE"),
        FeatureObservation("1111", "close", 999, date(2026, 7, 17), datetime(2026, 7, 18, 8, tzinfo=TAIPEI), "TWSE", revision_id="future-correction"),
    )
    snapshot = PointInTimeDatasetBuilder(
        security_master=_master(),
        observations=observations,
        expected_features=("close", "volume"),
        critical_features=("close",),
    ).build(decision_at=decision_at, horizon=5)

    assert [row.security.symbol for row in snapshot.rows] == ["1111"]
    assert snapshot.rows[0].features["close"] == 11
    assert snapshot.rows[0].missing_features == ("volume",)
    assert snapshot.excluded_future_observation_count == 1
    assert snapshot.audit_available_at() == ()


def test_historical_security_remains_in_universe_before_delisting() -> None:
    master = _master()

    historical = master.common_stock_universe(date(2026, 7, 17), horizon=5)
    after_validity = master.common_stock_universe(date(2026, 8, 2), horizon=5)

    assert [record.symbol for record in historical.securities] == ["1111"]
    assert after_validity.securities == ()


def test_fold_imputer_rejects_data_released_after_training_end() -> None:
    scope = FoldFitScope("fold-1", datetime(2025, 12, 31, tzinfo=TAIPEI))
    imputer = CrossSectionalMedianImputer()

    with pytest.raises(ValueError, match="training end"):
        imputer.fit(
            ({"x": 1.0},),
            feature_names=("x",),
            scope=scope,
            row_available_ats=(datetime(2026, 1, 1, tzinfo=TAIPEI),),
        )

    imputer.fit(
        ({"x": 1.0}, {"x": 3.0}),
        feature_names=("x",),
        scope=scope,
        row_available_ats=(
            datetime(2025, 1, 1, tzinfo=TAIPEI),
            datetime(2025, 1, 2, tzinfo=TAIPEI),
        ),
    )
    assert imputer.transform(
        ({"x": None},), decision_dates=(date(2026, 1, 2),)
    ) == [{"x": 2.0, "x__missing": 1.0}]

    same_day = date(2026, 1, 2)
    assert imputer.transform(
        ({"x": 4.0}, {"x": None}, {"x": 8.0}),
        decision_dates=(same_day, same_day, same_day),
    )[1] == {"x": 6.0, "x__missing": 1.0}
