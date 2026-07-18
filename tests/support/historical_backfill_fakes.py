"""Deterministic test doubles for historical backfill orchestration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from typing import final
from uuid import UUID

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.historical_backfill_contracts import (
    HistoricalBackfillSnapshot,
    HistoricalBackfillTask,
)
from src.data.ingestion.historical_backfill_coordinator import (
    HistoricalBackfillCoordinator,
)
from src.data.ingestion.historical_backfill_settings import HistoricalBackfillSettings
from src.data.ingestion.historical_daily_bar_import_contracts import (
    HistoricalSymbolLandingResult,
)
from src.data.providers.contracts import ProviderPayload
from src.data.providers.errors import ProviderHttpError


def payload(dataset: str, body: object) -> ProviderPayload:
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return ProviderPayload(
        provider="FINMIND",
        dataset=dataset,
        source_version="api.v4",
        source_url="https://api.finmindtrade.com/api/v4/data",
        retrieved_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        payload_sha256=sha256(encoded).hexdigest(),
        payload=body,
    )


def snapshot(
    *,
    database_bytes: int = 53_000_000,
    twse: int = 1,
    tpex: int = 1,
    etf_tasks: int = 1,
    etf: int = 1,
) -> HistoricalBackfillSnapshot:
    return HistoricalBackfillSnapshot(
        database_bytes=database_bytes,
        landing_bytes=36_000_000,
        landing_symbols=20,
        task_count=twse + tpex + etf_tasks,
        twse_common_remaining=twse,
        tpex_common_remaining=tpex,
        etf_task_count=etf_tasks,
        etf_remaining=etf,
        succeeded=0,
        exhausted=0,
    )


def task(
    task_id: int, symbol: str, market: str, asset_type: str
) -> HistoricalBackfillTask:
    priority = 10 if market == "TWSE" and asset_type == "COMMON_STOCK" else 20
    if asset_type == "ETF":
        priority = 30
    return HistoricalBackfillTask(
        task_id=task_id,
        symbol=symbol,
        display_name=None,
        market=market,
        asset_type=asset_type,
        priority=priority,
        start_date=date(2021, 7, 19),
        end_date=date(2026, 7, 17),
        attempt_count=1,
        max_attempts=5,
    )


class FakeProvider:
    def __init__(self, *, used: int = 10, limit: int = 600) -> None:
        self.used: int = used
        self.limit: int = limit
        self.calls: list[str] = []

    def fetch_quota(self) -> ProviderPayload:
        self.calls.append("quota")
        return payload(
            "api_quota",
            {"user_count": self.used, "api_request_limit": self.limit},
        )

    def fetch(
        self,
        dataset: str,
        *,
        data_id: str | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> ProviderPayload:
        _ = (data_id, start_date, end_date)
        self.calls.append(dataset)
        return payload(
            dataset,
            {
                "status": 200,
                "data": [
                    {
                        "industry_category": "ETF",
                        "stock_id": "0050",
                        "stock_name": "元大台灣50",
                        "type": "twse",
                    }
                ],
            },
        )


class QuotaDeniedProvider(FakeProvider):
    def fetch_quota(self) -> ProviderPayload:  # pyright: ignore[reportImplicitOverride]
        raise ProviderHttpError(402, "https://api.web.finmindtrade.com/v2/user_info")


@final
class FakeRepository:
    def __init__(
        self,
        tasks: Sequence[HistoricalBackfillTask] = (),
        *,
        snapshots: Sequence[HistoricalBackfillSnapshot] = (),
    ) -> None:
        self.tasks: list[HistoricalBackfillTask] = list(tasks)
        self.snapshots: list[HistoricalBackfillSnapshot] = list(snapshots) or [
            snapshot()
        ]
        self.completed: list[tuple[str, bool, str | None]] = []
        self.etf_rows: list[dict[str, object]] = []
        self.ensure_calls: int = 0
        self.seed_common_calls: int = 0

    def ensure_finmind_source(self) -> None:
        self.ensure_calls += 1

    def seed_common(
        self, *, start_date: date, end_date: date, selection_snapshot_at: datetime
    ) -> int:
        _ = (start_date, end_date, selection_snapshot_at)
        self.seed_common_calls += 1
        return 0

    def seed_etfs(
        self,
        rows: Sequence[Mapping[str, object]],
        *,
        start_date: date,
        end_date: date,
        selection_snapshot_at: datetime,
    ) -> int:
        _ = (start_date, end_date, selection_snapshot_at)
        self.etf_rows = [dict(row) for row in rows]
        return len(rows)

    def claim_one(
        self, *, worker_id: str, claim_token: UUID, lease_seconds: int
    ) -> HistoricalBackfillTask | None:
        _ = (worker_id, claim_token, lease_seconds)
        return self.tasks.pop(0) if self.tasks else None

    def complete(
        self,
        *,
        task: HistoricalBackfillTask,
        claim_token: UUID,
        success: bool,
        latest_trade_date: str | None = None,
        fetched_rows: int = 0,
        landed_rows: int = 0,
        quarantined_rows: int = 0,
        quarantine_issues: int = 0,
        retry_after_seconds: int,
        error_code: str | None = None,
    ) -> None:
        _ = (
            claim_token,
            latest_trade_date,
            fetched_rows,
            landed_rows,
            quarantined_rows,
            quarantine_issues,
            retry_after_seconds,
        )
        self.completed.append((task.symbol, success, error_code))

    def snapshot(
        self, *, start_date: date, end_date: date
    ) -> HistoricalBackfillSnapshot:
        _ = (start_date, end_date)
        if len(self.snapshots) > 1:
            return self.snapshots.pop(0)
        return self.snapshots[0]


@final
class FakeLandingService:
    def __init__(self, errors: Mapping[str, IngestionError] | None = None) -> None:
        self.errors: dict[str, IngestionError] = dict(errors or {})
        self.symbols: list[str] = []
        self.refresh_calls: int = 0

    def land_symbol(
        self, *, symbol: str, start_date: date, end_date: date
    ) -> HistoricalSymbolLandingResult:
        _ = (start_date, end_date)
        self.symbols.append(symbol)
        if symbol in self.errors:
            raise self.errors[symbol]
        return HistoricalSymbolLandingResult(
            symbol=symbol,
            fetched_rows=2,
            landed_rows=2,
            quarantined_rows=0,
            quarantine_issues=0,
            latest_trade_date="2026-07-17",
            source_payload_hash="0" * 64,
        )

    def refresh_home_status(self) -> None:
        self.refresh_calls += 1


@final
class Clock:
    def __init__(self) -> None:
        self.value: float = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def make_coordinator(
    provider: FakeProvider,
    repository: FakeRepository,
    landing: FakeLandingService,
    *,
    settings: HistoricalBackfillSettings | None = None,
) -> HistoricalBackfillCoordinator:
    clock = Clock()
    return HistoricalBackfillCoordinator(
        provider=provider,
        repository=repository,
        landing_service=landing,
        settings=settings or HistoricalBackfillSettings(),
        sleep_fn=clock.sleep,
        monotonic_fn=clock.monotonic,
        now_fn=lambda: datetime(2026, 7, 19, tzinfo=timezone.utc),
    )
