from __future__ import annotations

from src.data.ingestion.monthly_benchmark_ohlc_backfill import (
    MonthlyBenchmarkOhlcBackfillCoordinator,
)
from src.data.ingestion.taiex_ohlc_backfill_coordinator import (
    TAIEX_PROFILE,
    TaiexOhlcBackfillCoordinator,
)
from src.data.ingestion.tpex_ohlc_backfill_coordinator import (
    TPEX_PROFILE,
    TpexOhlcBackfillCoordinator,
)


def test_venue_adapters_share_one_monthly_orchestration_contract() -> None:
    assert issubclass(TaiexOhlcBackfillCoordinator, MonthlyBenchmarkOhlcBackfillCoordinator)
    assert issubclass(TpexOhlcBackfillCoordinator, MonthlyBenchmarkOhlcBackfillCoordinator)
    assert "run" not in TaiexOhlcBackfillCoordinator.__dict__
    assert "run" not in TpexOhlcBackfillCoordinator.__dict__


def test_venue_profiles_preserve_market_specific_scope_and_error_codes() -> None:
    assert (TAIEX_PROFILE.market, TAIEX_PROFILE.symbol) == ("TWSE", "TAIEX")
    assert TAIEX_PROFILE.source_dataset == "taiex_price_index_ohlc"
    assert TAIEX_PROFILE.invalid_scope_reason_code == (
        "TAIEX_OHLC_BACKFILL_TASK_SCOPE_INVALID"
    )
    assert TAIEX_PROFILE.fetch_failed_reason_code == "TAIEX_OHLC_FETCH_FAILED"

    assert (TPEX_PROFILE.market, TPEX_PROFILE.symbol) == ("TPEX", "TPEX_INDEX")
    assert TPEX_PROFILE.source_dataset == "tpex_price_index_ohlc"
    assert TPEX_PROFILE.invalid_scope_reason_code == (
        "TPEX_OHLC_BACKFILL_TASK_SCOPE_INVALID"
    )
    assert TPEX_PROFILE.fetch_failed_reason_code == "TPEX_OHLC_FETCH_FAILED"
