from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.security_snapshot import (
    SNAPSHOT_SOURCE_VERSION,
    normalize_current_security_snapshot,
    snapshot_revision_hash,
)
from tests.support.security_snapshot_fixtures import (
    provider_payload,
    tpex_bundle,
    twse_bundle,
)


SNAPSHOT_DATE = date(2026, 7, 18)


def test_twse_snapshot_maps_current_flags_and_whole_day_suspension() -> None:
    bundle = twse_bundle(
        profiles=[
            {"出表日期": "1150718", "公司代號": "2330", "產業別": "24"},
            {"出表日期": "1150718", "公司代號": "2317", "產業別": "25"},
        ],
        restrictions=[{"Code": "2330", "PeriodicCallAuctionTrading": "是"}],
        suspended=[
            {
                "Code": "2317",
                "TradingHaltDate": "1150718",
                "TradingHaltTime": "08:00:00",
                "TradingResumptionDate": "",
            }
        ],
        attention=[{"Date": "1150718", "Code": "2330"}],
        disposals=[
            {"Code": "2330", "DispositionPeriod": "115/07/18～115/07/20"}
        ],
    )
    result = normalize_current_security_snapshot(
        bundle,
        market="TWSE",
        snapshot_date=SNAPSHOT_DATE,
        source_id=7,
        security_ids={("TWSE", "2330"): 1, ("TWSE", "2317"): 2},
    )
    by_id = {row["security_id"]: row for row in result.rows}

    assert by_id[1]["trading_status"] == "ACTIVE"
    assert by_id[1]["attention_flag"] is True
    assert by_id[1]["disposal_flag"] is True
    assert by_id[1]["altered_trading_method_flag"] is True
    assert by_id[1]["periodic_auction_flag"] is True
    assert by_id[2]["trading_status"] == "SUSPENDED"
    assert by_id[2]["suspended_flag"] is True
    assert result.excluded_intraday_suspensions == 0


def test_tpex_stopped_status_precedes_suspended_status() -> None:
    bundle = tpex_bundle(
        profiles=[
            {
                "Date": "20260718",
                "SecuritiesCompanyCode": "3000",
                "SecuritiesIndustryCode": "24",
            }
        ],
        restrictions=[
            {
                "Date": "20260718",
                "SecuritiesCompanyCode": "3000",
                "AlteredTrading": "Y",
                "PeriodicTrading": "Y",
                "SuspensionOfTrading": "Y",
            }
        ],
        suspended=[
            {
                "SecuritiesCompanyCode": "3000",
                "DateOfSuspendedTrading": "20260718",
                "TimeOfSuspendedTrading": "08:00",
                "DateOfResumedTrading": "",
            }
        ],
    )
    row = normalize_current_security_snapshot(
        bundle,
        market="TPEX",
        snapshot_date=SNAPSHOT_DATE,
        source_id=8,
        security_ids={("TPEX", "3000"): 3},
    ).rows[0]

    assert row["trading_status"] == "STOPPED"
    assert row["suspended_flag"] is False


def test_intraday_suspension_and_unverified_full_delivery_remain_unknown() -> None:
    bundle = twse_bundle(
        profiles=[
            {"出表日期": "1150718", "公司代號": "2330", "產業別": "24"}
        ],
        suspended=[
            {
                "Code": "2330",
                "TradingHaltDate": "1150718",
                "TradingHaltTime": "10:30:00",
                "TradingResumptionDate": "",
            }
        ],
    )
    result = normalize_current_security_snapshot(
        bundle,
        market="TWSE",
        snapshot_date=SNAPSHOT_DATE,
        source_id=7,
        security_ids={("TWSE", "2330"): 1},
    )
    row = result.rows[0]

    assert row["trading_status"] == "UNKNOWN"
    assert row["suspended_flag"] is None
    assert row["full_cash_delivery_flag"] is None
    assert row["record_kind"] == "CURRENT_DAILY_SNAPSHOT"
    assert row["snapshot_date"] == "2026-07-18"
    assert row["effective_to"] == "2026-07-19"
    assert row["source_version"] == SNAPSHOT_SOURCE_VERSION
    assert len(str(row["source_revision_hash"])) == 64
    assert result.excluded_intraday_suspensions == 1


def test_snapshot_rejects_wrong_source_contract_and_backdating() -> None:
    bundle = twse_bundle(
        profiles=[
            {"出表日期": "1150718", "公司代號": "2330", "產業別": "24"}
        ]
    )
    wrong_source = replace(
        bundle,
        attention=provider_payload("TPEX", "attention", []),
    )
    with pytest.raises(IngestionError) as wrong:
        normalize_current_security_snapshot(
            wrong_source,
            market="TWSE",
            snapshot_date=SNAPSHOT_DATE,
            source_id=1,
            security_ids={("TWSE", "2330"): 1},
        )
    assert wrong.value.reason_code == "SECURITY_SNAPSHOT_SOURCE_INVALID"

    yesterday = datetime(2026, 7, 17, 6, tzinfo=timezone.utc)
    backdated = replace(
        bundle,
        attention=provider_payload(
            "TWSE", "attention", [], retrieved_at=yesterday
        ),
    )
    with pytest.raises(IngestionError) as mismatch:
        normalize_current_security_snapshot(
            backdated,
            market="TWSE",
            snapshot_date=SNAPSHOT_DATE,
            source_id=1,
            security_ids={("TWSE", "2330"): 1},
        )
    assert mismatch.value.reason_code == "SECURITY_SNAPSHOT_DATE_MISMATCH"


def test_composite_revision_hash_changes_when_any_payload_changes() -> None:
    bundle = twse_bundle(
        profiles=[
            {"出表日期": "1150718", "公司代號": "2330", "產業別": "24"}
        ]
    )
    changed = replace(
        bundle,
        attention=provider_payload(
            "TWSE", "attention", [{"Date": "1150718", "Code": "2330"}]
        ),
    )

    assert snapshot_revision_hash(bundle) == snapshot_revision_hash(bundle)
    assert snapshot_revision_hash(bundle) != snapshot_revision_hash(changed)


def test_invalid_suspension_range_and_disposal_period_fail_closed() -> None:
    profiles = [{"出表日期": "1150718", "公司代號": "2330", "產業別": "24"}]
    invalid_suspension = twse_bundle(
        profiles=profiles,
        suspended=[
            {
                "Code": "2330",
                "TradingHaltDate": "1150718",
                "TradingHaltTime": "08:00",
                "TradingResumptionDate": "1150718",
            }
        ],
    )
    with pytest.raises(IngestionError) as range_error:
        normalize_current_security_snapshot(
            invalid_suspension,
            market="TWSE",
            snapshot_date=SNAPSHOT_DATE,
            source_id=1,
            security_ids={("TWSE", "2330"): 1},
        )
    assert range_error.value.reason_code == "SECURITY_EVENT_RANGE_INVALID"

    invalid_disposal = twse_bundle(
        profiles=profiles,
        disposals=[{"Code": "2330", "DispositionPeriod": "unknown"}],
    )
    with pytest.raises(IngestionError) as disposal_error:
        normalize_current_security_snapshot(
            invalid_disposal,
            market="TWSE",
            snapshot_date=SNAPSHOT_DATE,
            source_id=1,
            security_ids={("TWSE", "2330"): 1},
        )
    assert disposal_error.value.reason_code == "SECURITY_DISPOSAL_PERIOD_INVALID"
