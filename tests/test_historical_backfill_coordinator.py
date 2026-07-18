from datetime import date

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.historical_backfill_settings import HistoricalBackfillSettings
from src.data.ingestion.historical_backfill_runtime import finmind_quota_counters
from tests.support.historical_backfill_fakes import (
    Clock,
    FakeLandingService,
    FakeProvider,
    FakeRepository,
    QuotaDeniedProvider,
    make_coordinator,
    payload,
    snapshot,
    task,
)


def test_quota_counters_reject_inconsistent_documented_values() -> None:
    assert finmind_quota_counters(
        payload("api_quota", {"user_count": 12, "api_request_limit": 600})
    ) == (12, 600)
    try:
        _ = finmind_quota_counters(
            payload("api_quota", {"user_count": 601, "api_request_limit": 600})
        )
    except IngestionError as error:
        assert error.reason_code == "FINMIND_QUOTA_PAYLOAD_INVALID"
    else:
        raise AssertionError("invalid quota counters must fail closed")


def test_quota_reserve_stops_before_claiming_a_task() -> None:
    repository = FakeRepository([task(1, "2330", "TWSE", "COMMON_STOCK")])
    summary = make_coordinator(
        FakeProvider(used=580, limit=600), repository, FakeLandingService()
    ).run(
        start_date=date(2021, 7, 19),
        end_date=date(2026, 7, 17),
        max_tasks=60,
        worker_id="test",
    )
    assert summary.outcome == "QUOTA_WAIT"
    assert repository.completed == []


def test_provider_quota_denial_is_a_safe_wait_not_a_failed_run() -> None:
    repository = FakeRepository([task(1, "2330", "TWSE", "COMMON_STOCK")])
    summary = make_coordinator(
        QuotaDeniedProvider(), repository, FakeLandingService()
    ).run(
        start_date=date(2021, 7, 19),
        end_date=date(2026, 7, 17),
        max_tasks=60,
        worker_id="test",
    )
    assert summary.outcome == "QUOTA_WAIT"
    assert summary.attempted_tasks == 0
    assert repository.completed == []


def test_capacity_guard_stops_before_claiming_a_task() -> None:
    repository = FakeRepository(
        [task(1, "2330", "TWSE", "COMMON_STOCK")],
        snapshots=[snapshot(database_bytes=420_000_000)],
    )
    summary = make_coordinator(FakeProvider(), repository, FakeLandingService()).run(
        start_date=date(2021, 7, 19),
        end_date=date(2026, 7, 17),
        max_tasks=60,
        worker_id="test",
    )
    assert summary.outcome == "CAPACITY_GUARD"
    assert repository.completed == []


def test_r2_target_uses_object_budget_instead_of_postgres_byte_budget() -> None:
    repository = FakeRepository(
        [task(1, "2330", "TWSE", "COMMON_STOCK")],
        snapshots=[snapshot(database_bytes=420_000_000)],
    )
    settings = HistoricalBackfillSettings(
        storage_target="R2",
        max_archive_objects_per_run=1,
    )

    summary = make_coordinator(
        FakeProvider(),
        repository,
        FakeLandingService(),
        settings=settings,
    ).run(
        start_date=date(2021, 7, 19),
        end_date=date(2026, 7, 17),
        max_tasks=1,
        worker_id="test",
    )

    assert summary.outcome == "PROGRESSED"
    assert summary.storage_task_budget == 1
    assert repository.completed == [("2330", True, None)]


def test_r2_workers_skip_intermediate_postgres_storage_snapshots() -> None:
    repository = FakeRepository(
        [task(index, f"{index:04d}", "TWSE", "COMMON_STOCK") for index in range(1, 21)]
    )
    settings = HistoricalBackfillSettings(
        storage_target="R2",
        max_archive_objects_per_run=20,
    )

    summary = make_coordinator(
        FakeProvider(),
        repository,
        FakeLandingService(),
        settings=settings,
    ).run(
        start_date=date(2021, 7, 19),
        end_date=date(2026, 7, 17),
        max_tasks=20,
        worker_id="test",
    )

    assert summary.succeeded_tasks == 20
    assert repository.snapshot_calls == 2


def test_each_symbol_is_completed_independently_and_order_is_preserved() -> None:
    tasks = [
        task(1, "2330", "TWSE", "COMMON_STOCK"),
        task(2, "6488", "TPEX", "COMMON_STOCK"),
        task(3, "0050", "TWSE", "ETF"),
    ]
    repository = FakeRepository(tasks)
    landing = FakeLandingService(
        {"6488": IngestionError("HISTORICAL_DAILY_BAR_EMPTY_RESPONSE", "empty")}
    )
    summary = make_coordinator(FakeProvider(), repository, landing).run(
        start_date=date(2021, 7, 19),
        end_date=date(2026, 7, 17),
        max_tasks=3,
        worker_id="test",
    )
    assert landing.symbols == ["2330", "6488", "0050"]
    assert repository.completed == [
        ("2330", True, None),
        ("6488", False, "HISTORICAL_DAILY_BAR_EMPTY_RESPONSE"),
        ("0050", True, None),
    ]
    assert summary.succeeded_tasks == 2
    assert summary.retried_tasks == 1
    assert landing.refresh_calls == 1


def test_worker_can_defer_home_status_refresh_to_single_finalizer() -> None:
    repository = FakeRepository([task(1, "2330", "TWSE", "COMMON_STOCK")])
    landing = FakeLandingService()
    settings = HistoricalBackfillSettings(refresh_home_status=False)

    summary = make_coordinator(
        FakeProvider(),
        repository,
        landing,
        settings=settings,
    ).run(
        start_date=date(2021, 7, 19),
        end_date=date(2026, 7, 17),
        max_tasks=1,
        worker_id="test",
    )

    assert summary.succeeded_tasks == 1
    assert landing.refresh_calls == 0


def test_pacing_uses_logical_request_start_with_four_second_landing_latency() -> None:
    clock = Clock()
    repository = FakeRepository(
        [
            task(1, "2330", "TWSE", "COMMON_STOCK"),
            task(2, "2317", "TWSE", "COMMON_STOCK"),
        ]
    )
    landing = FakeLandingService(latency_fn=lambda _: clock.advance(4.0))

    _ = make_coordinator(FakeProvider(), repository, landing, clock=clock).run(
        start_date=date(2021, 7, 19),
        end_date=date(2026, 7, 17),
        max_tasks=2,
        worker_id="test",
    )

    # The initial 6.5 seconds separates the quota call from the first symbol.
    # Four seconds of logical-call latency leave only 2.5 seconds to the next start.
    assert clock.sleep_calls == [6.5, 2.5]


def test_pacing_does_not_sleep_after_latency_reaches_the_logical_interval() -> None:
    clock = Clock()
    repository = FakeRepository(
        [
            task(1, "2330", "TWSE", "COMMON_STOCK"),
            task(2, "2317", "TWSE", "COMMON_STOCK"),
        ]
    )
    landing = FakeLandingService(latency_fn=lambda _: clock.advance(6.5))

    _ = make_coordinator(FakeProvider(), repository, landing, clock=clock).run(
        start_date=date(2021, 7, 19),
        end_date=date(2026, 7, 17),
        max_tasks=2,
        worker_id="test",
    )

    assert clock.sleep_calls == [6.5]


def test_etf_universe_is_only_seeded_after_common_stage_finishes() -> None:
    common_repository = FakeRepository(
        snapshots=[snapshot(twse=1, tpex=0, etf_tasks=0, etf=0)]
    )
    common_provider = FakeProvider()
    _ = make_coordinator(common_provider, common_repository, FakeLandingService()).run(
        start_date=date(2021, 7, 19),
        end_date=date(2026, 7, 17),
        max_tasks=1,
        worker_id="test",
    )
    assert common_provider.calls == ["quota"]
    assert common_repository.etf_rows == []

    etf_repository = FakeRepository(
        snapshots=[snapshot(twse=0, tpex=0, etf_tasks=0, etf=0)]
    )
    etf_provider = FakeProvider()
    _ = make_coordinator(etf_provider, etf_repository, FakeLandingService()).run(
        start_date=date(2021, 7, 19),
        end_date=date(2026, 7, 17),
        max_tasks=1,
        worker_id="test",
    )
    assert etf_provider.calls == ["quota", "securities"]
    assert etf_repository.etf_rows == [
        {"source_symbol": "0050", "display_name": "元大台灣50", "market": "TWSE"}
    ]
