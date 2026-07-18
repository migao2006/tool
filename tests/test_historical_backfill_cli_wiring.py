from typing import cast

import pytest

from scripts import backfill_historical_daily_bars
from src.data.ingestion.historical_backfill_settings import HistoricalBackfillSettings
from src.data.ingestion.supabase_writer import SupabaseWriter
from src.data.object_storage.r2_client import R2Client


def test_supabase_target_does_not_require_r2_configuration() -> None:
    service = backfill_historical_daily_bars.build_archive_service(
        settings=HistoricalBackfillSettings(storage_target="SUPABASE"),
        writer=cast(SupabaseWriter, object()),
    )

    assert service is None


def test_r2_target_builds_archive_service_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = cast(R2Client, object())
    writer = cast(SupabaseWriter, object())

    class FakeR2Client:
        @classmethod
        def from_env(cls) -> R2Client:
            return store

    monkeypatch.setattr(backfill_historical_daily_bars, "R2Client", FakeR2Client)

    service = backfill_historical_daily_bars.build_archive_service(
        settings=HistoricalBackfillSettings(
            storage_target="R2",
            max_archive_object_bytes=12_500_000,
        ),
        writer=writer,
    )

    assert service is not None
    assert service.store is store
    assert service.repository.writer is writer
    assert service.max_object_bytes == 12_500_000
