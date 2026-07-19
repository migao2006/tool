from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import final

import pytest

from scripts import backfill_historical_supplemental
from src.data.ingestion.historical_backfill_settings import HistoricalBackfillSettings
from src.data.ingestion.historical_supplemental_backfill_contracts import (
    HistoricalSupplementalBackfillSnapshot,
    HistoricalSupplementalBackfillSummary,
)
from src.data.ingestion.historical_supplemental_backfill_coordinator import (
    HistoricalSupplementalBackfillCoordinator,
)
from src.data.ingestion.historical_supplemental_backfill_repository import (
    HistoricalSupplementalBackfillRepository,
)
from src.data.ingestion.historical_daily_bar_import_contracts import (
    HistoricalSymbolLandingResult,
)
from src.data.providers.errors import ProviderHttpError
from tests.support.historical_backfill_fakes import FakeProvider


@final
class _Writer:
    def __init__(
        self,
        before: HistoricalSupplementalBackfillSnapshot,
        after: HistoricalSupplementalBackfillSnapshot,
    ) -> None:
        self._snapshots: list[HistoricalSupplementalBackfillSnapshot] = [
            before,
            after,
        ]

    def upsert(
        self,
        table: str,
        rows: Sequence[Mapping[str, object]],
        *,
        on_conflict: str,
        select: str | None = None,
        return_rows: bool = False,
        preserve_existing: bool = False,
    ) -> list[dict[str, object]]:
        _ = (
            table,
            rows,
            on_conflict,
            select,
            return_rows,
            preserve_existing,
        )
        return []

    def rpc(self, function_name: str, parameters: Mapping[str, object]) -> object:
        _ = parameters
        if function_name == "seed_historical_supplemental_twse_tasks":
            return 0
        if function_name == "claim_historical_supplemental_backfill_task":
            return []
        if function_name == "historical_supplemental_backfill_snapshot":
            snapshot = self._snapshots.pop(0)
            return [
                {
                    "task_count": snapshot.task_count,
                    "adjusted_bars_remaining": snapshot.adjusted_bars_remaining,
                    "institutional_flows_remaining": (
                        snapshot.institutional_flows_remaining
                    ),
                    "margin_short_remaining": snapshot.margin_short_remaining,
                    "succeeded": snapshot.succeeded,
                    "exhausted": snapshot.exhausted,
                }
            ]
        raise AssertionError(f"unexpected RPC: {function_name}")


@final
class _UnusedLandingService:
    def land_symbol(
        self,
        *,
        dataset: str,
        symbol: str,
        start_date: date,
        end_date: date,
        scheduled_market: str,
        asset_type: str,
        backfill_task_id: int | None,
    ) -> HistoricalSymbolLandingResult:
        _ = (
            dataset,
            symbol,
            start_date,
            end_date,
            scheduled_market,
            asset_type,
            backfill_task_id,
        )
        raise AssertionError("no task should be claimed in this test")


def _snapshot(
    *, remaining: int = 0, exhausted: int = 0
) -> HistoricalSupplementalBackfillSnapshot:
    return HistoricalSupplementalBackfillSnapshot(
        task_count=remaining + exhausted,
        adjusted_bars_remaining=remaining,
        institutional_flows_remaining=0,
        margin_short_remaining=0,
        succeeded=0,
        exhausted=exhausted,
    )


def _run(
    after: HistoricalSupplementalBackfillSnapshot,
) -> HistoricalSupplementalBackfillSummary:
    repository = HistoricalSupplementalBackfillRepository(
        _Writer(_snapshot(remaining=after.remaining), after)
    )
    coordinator = HistoricalSupplementalBackfillCoordinator(
        provider=FakeProvider(),
        repository=repository,
        landing_service=_UnusedLandingService(),
        settings=HistoricalBackfillSettings(
            storage_target="R2",
            pacing_floor_seconds=0,
        ),
        sleep_fn=lambda _: None,
        monotonic_fn=lambda: 0,
        now_fn=lambda: datetime(2026, 7, 19, tzinfo=timezone.utc),
    )
    return coordinator.run(
        start_date=date(2021, 7, 19),
        end_date=date(2026, 7, 17),
        max_tasks=1,
        worker_id="test",
    )


@pytest.mark.parametrize("remaining", [0, 1])
def test_exhausted_tasks_are_never_reported_as_completed(remaining: int) -> None:
    summary = _run(_snapshot(remaining=remaining, exhausted=1))

    assert summary.outcome == "EXHAUSTED_TASKS"
    assert summary.exhausted_tasks == 1
    assert "HISTORICAL_SUPPLEMENTAL_TASKS_EXHAUSTED" in summary.reason_codes


def test_clean_terminal_snapshot_remains_completed() -> None:
    summary = _run(_snapshot())

    assert summary.outcome == "COMPLETED"
    assert "HISTORICAL_SUPPLEMENTAL_TASKS_EXHAUSTED" not in summary.reason_codes


def test_quota_probe_does_not_hide_existing_exhausted_tasks() -> None:
    class _QuotaProvider:
        def fetch_quota(self):
            raise ProviderHttpError(
                402,
                "https://api.web.finmindtrade.com/v2/user_info",
            )

    before = _snapshot(remaining=1, exhausted=1)
    repository = HistoricalSupplementalBackfillRepository(_Writer(before, before))
    coordinator = HistoricalSupplementalBackfillCoordinator(
        provider=_QuotaProvider(),
        repository=repository,
        landing_service=_UnusedLandingService(),
        settings=HistoricalBackfillSettings(
            storage_target="R2",
            pacing_floor_seconds=0,
        ),
        sleep_fn=lambda _: None,
        monotonic_fn=lambda: 0,
        now_fn=lambda: datetime(2026, 7, 19, tzinfo=timezone.utc),
    )

    summary = coordinator.run(
        start_date=date(2021, 7, 19),
        end_date=date(2026, 7, 17),
        max_tasks=1,
        worker_id="quota-test",
    )

    assert summary.outcome == "EXHAUSTED_TASKS"
    assert summary.exhausted_tasks == 1
    assert "FINMIND_QUOTA_WAIT" in summary.reason_codes
    assert "HISTORICAL_SUPPLEMENTAL_TASKS_EXHAUSTED" in summary.reason_codes


def test_cli_writes_exhausted_summary_before_returning_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = _run(_snapshot(exhausted=1))

    @final
    class _ProviderSettings:
        finmind_token: str = "unused"
        supabase_url: str = "https://example.supabase.co"
        supabase_service_role_key: str = "unused"
        timeout_seconds: float = 1.0

        @classmethod
        def from_env(cls) -> "_ProviderSettings":
            return cls()

    @final
    class _RuntimeSettings:
        @classmethod
        def from_env(cls) -> HistoricalBackfillSettings:
            return HistoricalBackfillSettings(storage_target="R2")

    @final
    class _R2Client:
        @classmethod
        def from_env(cls) -> object:
            return object()

    @final
    class _Coordinator:
        def __init__(self, **_: object) -> None:
            pass

        def run(self, **_: object) -> HistoricalSupplementalBackfillSummary:
            return summary

    def _object_factory(*args: object, **kwargs: object) -> object:
        _ = (args, kwargs)
        return object()

    monkeypatch.setattr(
        backfill_historical_supplemental,
        "ApiProviderSettings",
        _ProviderSettings,
    )
    monkeypatch.setattr(
        backfill_historical_supplemental,
        "HistoricalBackfillSettings",
        _RuntimeSettings,
    )
    monkeypatch.setattr(
        backfill_historical_supplemental,
        "FinMindClient",
        _object_factory,
    )
    monkeypatch.setattr(
        backfill_historical_supplemental,
        "SupabaseWriter",
        _object_factory,
    )
    monkeypatch.setattr(backfill_historical_supplemental, "R2Client", _R2Client)
    for name in (
        "HistoricalArchiveRepository",
        "HistoricalDailyBarArchiveService",
        "HistoricalSupplementalBackfillRepository",
        "HistoricalSupplementalLandingService",
    ):
        monkeypatch.setattr(
            backfill_historical_supplemental,
            name,
            _object_factory,
        )
    monkeypatch.setattr(
        backfill_historical_supplemental,
        "HistoricalSupplementalBackfillCoordinator",
        _Coordinator,
    )
    output = tmp_path / "summary.json"

    exit_code = backfill_historical_supplemental.main(
        [
            "--start-date",
            "2021-07-19",
            "--end-date",
            "2026-07-17",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 1
    assert json.loads(output.read_text(encoding="utf-8"))["outcome"] == (
        "EXHAUSTED_TASKS"
    )
