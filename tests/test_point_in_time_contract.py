from dataclasses import replace
from datetime import date, datetime, timezone
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


TAIPEI = ZoneInfo("Asia/Taipei")
NEW_YORK = ZoneInfo("America/New_York")
REVISION_A = "a" * 64
REVISION_B = "b" * 64


def _security(**overrides: object) -> SecurityRecord:
    values: dict[str, object] = {
        "security_id": 1,
        "listing_period_id": "TWSE:1111:2020-01-01",
        "symbol": "1111",
        "name": "Example",
        "market": Market.TWSE,
        "industry": "Semiconductor",
        "asset_type": AssetType.COMMON_STOCK,
        "valid_from": date(2020, 1, 1),
        "available_at": datetime(2020, 1, 1, tzinfo=TAIPEI),
        "first_observed_at": datetime(2020, 1, 1, tzinfo=TAIPEI),
        "available_at_basis": "VERSIONED_SNAPSHOT",
        "point_in_time_status": "VERIFIED",
        "usage_scope": "POINT_IN_TIME_IDENTITY",
        "reason_codes": (),
        "source_id": 1,
        "source_version": "2020-v1",
        "source_revision_hash": REVISION_A,
        "trading_status": TradingStatus.ACTIVE,
    }
    values.update(overrides)
    if "available_at" in overrides and "first_observed_at" not in overrides:
        values["first_observed_at"] = values["available_at"]
    return SecurityRecord(**values)


def _observation(**overrides: object) -> FeatureObservation:
    values: dict[str, object] = {
        "security_id": 1,
        "listing_period_id": "TWSE:1111:2020-01-01",
        "market": Market.TWSE,
        "symbol": "1111",
        "feature_name": "close",
        "value": 10,
        "data_date": date(2026, 7, 16),
        "available_at": datetime(2026, 7, 16, 15, 30, tzinfo=TAIPEI),
        "first_observed_at": datetime(2026, 7, 16, 15, 30, tzinfo=TAIPEI),
        "available_at_basis": "VERSIONED_SNAPSHOT",
        "point_in_time_status": "VERIFIED",
        "usage_scope": "POINT_IN_TIME_FEATURE",
        "reason_codes": (),
        "source": "TWSE",
        "source_version": "2026-07-16",
        "source_revision_hash": REVISION_A,
    }
    values.update(overrides)
    if "available_at" in overrides and "first_observed_at" not in overrides:
        values["first_observed_at"] = values["available_at"]
    return FeatureObservation(**values)


def _master(*records: SecurityRecord) -> SecurityMaster:
    return SecurityMaster(
        records=records
        or (
            _security(valid_to=date(2026, 8, 1)),
            _security(
                security_id=2,
                listing_period_id="TWSE:0050:2020-01-01",
                symbol="0050",
                name="ETF",
                asset_type=AssetType.ETF,
            ),
        ),
        benchmarks=(
            BenchmarkAssignment(
                Market.TWSE,
                "TAIEX",
                "2026-v1",
                date(2020, 1, 1),
                datetime(2020, 1, 1, tzinfo=TAIPEI),
            ),
            BenchmarkAssignment(
                Market.TPEX,
                "TPEX",
                "2026-v1",
                date(2020, 1, 1),
                datetime(2020, 1, 1, tzinfo=TAIPEI),
            ),
        ),
    )


def test_market_aliases_persist_using_exchange_codes() -> None:
    assert Market.LISTED is Market.TWSE
    assert Market.OTC is Market.TPEX
    assert Market.LISTED.value == "TWSE"
    assert Market.OTC.value == "TPEX"


def test_security_source_contract_requires_aware_release_and_sha256() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _security(available_at=datetime(2020, 1, 1))
    with pytest.raises(ValueError, match="SHA-256"):
        _security(source_revision_hash="not-a-hash")


def test_us_same_day_close_is_excluded_before_it_occurs_in_taiwan() -> None:
    decision_at = datetime(2026, 7, 17, 17, tzinfo=TAIPEI)
    same_calendar_day_us_close = datetime(2026, 7, 17, 16, tzinfo=NEW_YORK)
    prior_us_close = datetime(2026, 7, 16, 16, tzinfo=NEW_YORK)

    assert feature_is_available(same_calendar_day_us_close, decision_at) is False
    assert feature_is_available(prior_us_close, decision_at) is True


def test_snapshot_uses_latest_period_revision_and_excludes_etf() -> None:
    decision_at = datetime(2026, 7, 17, 17, tzinfo=TAIPEI)
    observations = (
        _observation(),
        _observation(
            value=11,
            data_date=date(2026, 7, 17),
            available_at=datetime(2026, 7, 17, 15, 30, tzinfo=TAIPEI),
            source_version="2026-07-17",
            source_revision_hash=REVISION_B,
        ),
        _observation(
            value=999,
            data_date=date(2026, 7, 17),
            available_at=datetime(2026, 7, 18, 8, tzinfo=TAIPEI),
            source_version="2026-07-18-correction",
            source_revision_hash="c" * 64,
            revision_id="future-correction",
        ),
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


def test_later_old_period_correction_does_not_replace_newer_data_period() -> None:
    decision_at = datetime(2026, 7, 17, 17, tzinfo=TAIPEI)
    snapshot = PointInTimeDatasetBuilder(
        security_master=_master(),
        observations=(
            _observation(
                value=999,
                data_date=date(2026, 7, 16),
                available_at=datetime(2026, 7, 17, 16, tzinfo=TAIPEI),
                revision_id="late-old-correction",
                source_version="old-correction",
                source_revision_hash=REVISION_B,
            ),
            _observation(
                value=11,
                data_date=date(2026, 7, 17),
                available_at=datetime(2026, 7, 17, 15, 30, tzinfo=TAIPEI),
                source_version="new-period",
            ),
        ),
        expected_features=("close",),
    ).build(decision_at=decision_at)

    assert snapshot.rows[0].features["close"] == 11


def test_conflicting_same_timestamp_revisions_fail_closed() -> None:
    released_at = datetime(2026, 7, 17, 15, 30, tzinfo=TAIPEI)
    builder = PointInTimeDatasetBuilder(
        security_master=_master(),
        observations=(
            _observation(
                value=10,
                data_date=date(2026, 7, 17),
                available_at=released_at,
            ),
            _observation(
                value=11,
                data_date=date(2026, 7, 17),
                available_at=released_at,
                source_version="conflict",
                source_revision_hash=REVISION_B,
                revision_id="conflict",
            ),
        ),
        expected_features=("close",),
    )

    with pytest.raises(ValueError, match="conflicting feature revisions"):
        builder.build(decision_at=datetime(2026, 7, 17, 17, tzinfo=TAIPEI))


def test_observation_identity_mismatch_fails_closed() -> None:
    builder = PointInTimeDatasetBuilder(
        security_master=_master(),
        observations=(_observation(security_id=999),),
        expected_features=("close",),
    )

    with pytest.raises(ValueError, match="identity conflicts"):
        builder.build(decision_at=datetime(2026, 7, 17, 17, tzinfo=TAIPEI))


def test_taipei_date_is_derived_from_aware_decision_instant() -> None:
    # 16:30 UTC is already the next calendar day in Taiwan.
    decision_at = datetime(2026, 7, 17, 16, 30, tzinfo=timezone.utc)
    security = _security(
        valid_from=date(2026, 7, 18),
        listing_date=date(2026, 7, 18),
        available_at=datetime(2026, 7, 18, 0, 1, tzinfo=TAIPEI),
    )
    snapshot = PointInTimeDatasetBuilder(
        security_master=_master(security),
        observations=(
            _observation(
                data_date=date(2026, 7, 18),
                available_at=datetime(2026, 7, 18, 0, 5, tzinfo=TAIPEI),
            ),
        ),
        expected_features=("close",),
    ).build(decision_at=decision_at)

    assert snapshot.decision_date == date(2026, 7, 18)
    assert snapshot.rows[0].features["close"] == 10


def test_identity_unavailable_at_decision_is_not_in_universe() -> None:
    master = _master(_security(available_at=datetime(2026, 7, 18, 9, tzinfo=TAIPEI)))

    snapshot = master.common_stock_universe(
        date(2026, 7, 17),
        decision_at=datetime(2026, 7, 17, 17, tzinfo=TAIPEI),
    )

    assert snapshot.securities == ()


def test_security_master_selects_latest_released_bitemporal_revision() -> None:
    original = _security(
        name="Original name",
        available_at=datetime(2026, 7, 16, 10, tzinfo=TAIPEI),
        source_version="revision-1",
    )
    correction = replace(
        original,
        name="Corrected name",
        available_at=datetime(2026, 7, 17, 10, tzinfo=TAIPEI),
        first_observed_at=datetime(2026, 7, 17, 10, tzinfo=TAIPEI),
        source_version="revision-2",
        source_revision_hash=REVISION_B,
    )
    master = _master(original, correction)

    before_correction = master.record_for_listing_period(
        original.listing_period_id,
        date(2026, 7, 17),
        decision_at=datetime(2026, 7, 17, 9, tzinfo=TAIPEI),
    )
    after_correction = master.record_for_listing_period(
        original.listing_period_id,
        date(2026, 7, 17),
        decision_at=datetime(2026, 7, 17, 11, tzinfo=TAIPEI),
    )
    universe = master.common_stock_universe(
        date(2026, 7, 17),
        decision_at=datetime(2026, 7, 17, 11, tzinfo=TAIPEI),
    )

    assert before_correction is not None
    assert before_correction.name == "Original name"
    assert after_correction is not None
    assert after_correction.name == "Corrected name"
    assert universe.securities == (correction,)


def test_security_master_rejects_conflicting_same_timestamp_revisions() -> None:
    original = _security(
        available_at=datetime(2026, 7, 17, 10, tzinfo=TAIPEI),
        source_version="revision-1",
    )
    conflict = replace(
        original,
        name="Conflicting name",
        source_version="revision-2",
        source_revision_hash=REVISION_B,
    )

    with pytest.raises(ValueError, match="conflicting security-master revisions"):
        _master(original, conflict)


def test_market_symbol_resolution_disambiguates_cross_market_tickers() -> None:
    master = _master(
        _security(),
        _security(
            security_id=2,
            listing_period_id="TPEX:1111:2020-01-01",
            market=Market.TPEX,
            source_id=2,
        ),
    )
    decision_at = datetime(2026, 7, 17, 17, tzinfo=TAIPEI)

    assert (
        master.record_for_market_symbol(
            Market.TWSE,
            "1111",
            date(2026, 7, 17),
            decision_at=decision_at,
        ).security_id
        == 1
    )
    assert (
        master.record_for_market_symbol(
            Market.TPEX,
            "1111",
            date(2026, 7, 17),
            decision_at=decision_at,
        ).security_id
        == 2
    )


def test_same_market_symbol_can_be_reused_only_in_non_overlapping_periods() -> None:
    old_listing = _security(valid_to=date(2025, 1, 1))
    new_listing = _security(
        security_id=2,
        listing_period_id="TWSE:1111:2025-01-01",
        valid_from=date(2025, 1, 1),
        listing_date=date(2025, 1, 1),
        available_at=datetime(2025, 1, 1, tzinfo=TAIPEI),
    )
    master = _master(old_listing, new_listing)

    resolved = master.record_for_market_symbol(
        Market.TWSE,
        "1111",
        date(2026, 7, 17),
        decision_at=datetime(2026, 7, 17, 17, tzinfo=TAIPEI),
    )
    assert resolved is not None
    assert resolved.listing_period_id == "TWSE:1111:2025-01-01"

    with pytest.raises(ValueError, match="overlapping security-master ranges"):
        _master(
            old_listing,
            replace(
                new_listing,
                valid_from=date(2024, 1, 1),
                listing_date=date(2024, 1, 1),
                available_at=datetime(2024, 1, 1, tzinfo=TAIPEI),
                first_observed_at=datetime(2024, 1, 1, tzinfo=TAIPEI),
            ),
        )


def test_unverified_feature_is_excluded_even_when_available_before_decision() -> None:
    decision_at = datetime(2026, 7, 17, 17, tzinfo=TAIPEI)
    observation = _observation(
        available_at_basis="FIRST_OBSERVED_AT_RETRIEVAL",
        point_in_time_status="UNVERIFIED",
        usage_scope="FEATURE_RESEARCH_ONLY",
        reason_codes=("FIRST_OBSERVED_ONLY",),
    )

    snapshot = PointInTimeDatasetBuilder(
        security_master=_master(),
        observations=(observation,),
        expected_features=("close",),
        critical_features=("close",),
    ).build(decision_at=decision_at)

    assert snapshot.rows[0].features == {}
    assert snapshot.rows[0].missing_critical_features == ("close",)
    assert snapshot.excluded_unverified_observation_count == 1


def test_security_id_can_span_non_overlapping_listing_periods() -> None:
    old_listing = _security(valid_to=date(2025, 1, 1))
    new_listing = _security(
        listing_period_id="TPEX:1111:2025-01-01",
        market=Market.TPEX,
        valid_from=date(2025, 1, 1),
        listing_date=date(2025, 1, 1),
        available_at=datetime(2025, 1, 1, tzinfo=TAIPEI),
        source_id=2,
    )
    master = _master(old_listing, new_listing)

    before = master.record_for_security_id(
        1,
        date(2024, 12, 31),
        decision_at=datetime(2024, 12, 31, 17, tzinfo=TAIPEI),
    )
    after = master.record_for_security_id(
        1,
        date(2025, 1, 2),
        decision_at=datetime(2025, 1, 2, 17, tzinfo=TAIPEI),
    )

    assert before is not None and before.market is Market.TWSE
    assert after is not None and after.market is Market.TPEX


def test_security_id_cannot_have_overlapping_listing_periods() -> None:
    old_listing = _security(valid_to=date(2025, 2, 1))
    overlapping_listing = _security(
        listing_period_id="TPEX:1111:2025-01-01",
        market=Market.TPEX,
        valid_from=date(2025, 1, 1),
        listing_date=date(2025, 1, 1),
        available_at=datetime(2025, 1, 1, tzinfo=TAIPEI),
        source_id=2,
    )

    with pytest.raises(ValueError, match="security_id=1"):
        _master(old_listing, overlapping_listing)


def test_historical_security_remains_in_universe_before_delisting() -> None:
    master = _master()

    historical = master.common_stock_universe(
        date(2026, 7, 17),
        decision_at=datetime(2026, 7, 17, 17, tzinfo=TAIPEI),
        horizon=5,
    )
    after_validity = master.common_stock_universe(
        date(2026, 8, 2),
        decision_at=datetime(2026, 8, 2, 17, tzinfo=TAIPEI),
        horizon=5,
    )

    assert [record.symbol for record in historical.securities] == ["1111"]
    assert after_validity.securities == ()


def test_benchmark_assignment_is_unavailable_before_first_observation() -> None:
    master = _master()

    with pytest.raises(ValueError, match="expected one benchmark"):
        master.benchmark_for(
            Market.LISTED,
            date(2020, 1, 1),
            decision_at=datetime(2019, 12, 31, 23, 59, tzinfo=TAIPEI),
        )


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
    assert imputer.transform(({"x": None},), decision_dates=(date(2026, 1, 2),)) == [
        {"x": 2.0, "x__missing": 1.0}
    ]

    same_day = date(2026, 1, 2)
    assert imputer.transform(
        ({"x": 4.0}, {"x": None}, {"x": 8.0}),
        decision_dates=(same_day, same_day, same_day),
    )[1] == {"x": 6.0, "x__missing": 1.0}
