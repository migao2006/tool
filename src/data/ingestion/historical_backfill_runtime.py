"""Runtime ports and limit calculations for historical backfill workers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from math import ceil, floor
from typing import Protocol, cast
from uuid import UUID

from src.data.providers.contracts import ProviderPayload
from src.data.providers.errors import ProviderHttpError

from .contracts import IngestionError
from .historical_backfill_contracts import (
    HistoricalBackfillSnapshot,
    HistoricalBackfillTask,
)
from .historical_backfill_settings import HistoricalBackfillSettings
from .historical_daily_bar_import_contracts import HistoricalSymbolLandingResult


class BackfillProvider(Protocol):
    def fetch_quota(self) -> ProviderPayload: ...

    def fetch(
        self,
        dataset: str,
        *,
        data_id: str | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> ProviderPayload: ...


class BackfillRepository(Protocol):
    def ensure_finmind_source(self) -> None: ...

    def seed_common(
        self, *, start_date: date, end_date: date, selection_snapshot_at: datetime
    ) -> int: ...

    def seed_etfs(
        self,
        rows: tuple[dict[str, object], ...],
        *,
        start_date: date,
        end_date: date,
        selection_snapshot_at: datetime,
    ) -> int: ...

    def claim_one(
        self, *, worker_id: str, claim_token: UUID, lease_seconds: int
    ) -> HistoricalBackfillTask | None: ...

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
    ) -> None: ...

    def snapshot(
        self, *, start_date: date, end_date: date
    ) -> HistoricalBackfillSnapshot: ...


class BackfillLandingService(Protocol):
    def land_symbol(
        self,
        *,
        symbol: str,
        start_date: date,
        end_date: date,
        scheduled_market: str | None = None,
        asset_type: str | None = None,
        backfill_task_id: int | None = None,
    ) -> HistoricalSymbolLandingResult: ...

    def refresh_home_status(self) -> None: ...


def finmind_quota_counters(payload: ProviderPayload) -> tuple[int, int]:
    raw = cast(object, payload.payload)
    if not isinstance(raw, Mapping):
        raise IngestionError(
            "FINMIND_QUOTA_PAYLOAD_INVALID",
            "FinMind quota response must be an object",
        )
    body = cast(Mapping[str, object], raw)
    used = body.get("user_count")
    limit = body.get("api_request_limit")
    if (
        isinstance(used, bool)
        or not isinstance(used, int)
        or used < 0
        or isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit <= 0
        or used > limit
    ):
        raise IngestionError(
            "FINMIND_QUOTA_PAYLOAD_INVALID",
            "FinMind quota response contains invalid documented counters",
        )
    return used, limit


def storage_task_budget(
    snapshot: HistoricalBackfillSnapshot,
    settings: HistoricalBackfillSettings,
) -> int:
    if settings.storage_target == "R2":
        return settings.max_archive_objects_per_run
    remaining_bytes = max(settings.max_database_bytes - snapshot.database_bytes, 0)
    average_bytes = (
        snapshot.landing_bytes / snapshot.landing_symbols
        if snapshot.landing_symbols
        else 0
    )
    estimated_symbol_bytes = max(
        settings.minimum_symbol_bytes,
        ceil(average_bytes * settings.storage_safety_factor),
    )
    return max(floor(remaining_bytes / estimated_symbol_bytes), 0)


def is_quota_error(error: Exception) -> bool:
    return (
        isinstance(error, ProviderHttpError) and error.status_code in {402, 429}
    ) or getattr(error, "reason_code", "") in {
        "FINMIND_IMPORT_QUOTA_INSUFFICIENT",
        "FINMIND_REQUEST_LIMIT_EXCEEDED",
    }
