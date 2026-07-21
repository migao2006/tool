from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path

from src.data.ingestion.historical_backfill_repository import (
    HistoricalBackfillRepository,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260719054500_historical_delisted_backfill_queue.sql"
)


class RecordingWriter:
    def __init__(self) -> None:
        self.rpc_calls: list[tuple[str, Mapping[str, object]]] = []

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
        del table, rows, on_conflict, select, return_rows, preserve_existing
        return []

    def rpc(self, function_name: str, parameters: Mapping[str, object]) -> object:
        self.rpc_calls.append((function_name, parameters))
        return 62


def test_repository_calls_dedicated_delisted_seed_rpc() -> None:
    writer = RecordingWriter()
    selected_at = datetime(2026, 7, 19, 3, 0, tzinfo=timezone.utc)

    inserted = HistoricalBackfillRepository(writer).seed_delisted_common(
        start_date=date(2021, 7, 19),
        end_date=date(2026, 7, 17),
        selection_snapshot_at=selected_at,
    )

    assert inserted == 62
    assert writer.rpc_calls == [
        (
            "seed_historical_backfill_delisted_common_tasks",
            {
                "p_start_date": "2021-07-19",
                "p_end_date": "2026-07-17",
                "p_selection_snapshot_at": selected_at.isoformat(),
            },
        )
    ]


def test_migration_keeps_delisted_tasks_unlinked_and_research_only() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "official_delisting_registry_scheduling_only" in sql
    assert "asset_type = 'common_stock'" in sql
    assert "security_id is null" in sql
    assert "identity_unresolved" in sql
    assert "usage_scope = 'raw_landing_only'" in sql
    assert "system_status = 'research_only'" in sql
    assert "source_symbol ~ '^[0-9]{4}$'" in sql
    assert "source_symbol !~ '^(00|91)'" in sql
    assert "observation.first_observed_at <= p_selection_snapshot_at" in sql
    assert "observation.available_at <= p_selection_snapshot_at" in sql
    assert "join market_data.securities" not in sql


def test_migration_preserves_current_master_identity_requirement_and_priority() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "selection_basis = 'current_security_master_scheduling_only'" in sql
    assert "and security_id is not null" in sql
    assert "alter column priority" not in sql
    assert "drop column priority" not in sql


def test_delisted_seed_rpc_is_private_security_invoker() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    compact_sql = " ".join(sql.split())
    function = "seed_historical_backfill_delisted_common_tasks"

    assert "security invoker" in sql
    assert "security definer" not in sql
    assert f"revoke all on function market_data.{function}(" in compact_sql
    assert f"grant execute on function market_data.{function}(" in compact_sql
    assert ") to service_role;" in compact_sql
    assert "to anon" not in compact_sql
    assert "to authenticated" not in compact_sql
