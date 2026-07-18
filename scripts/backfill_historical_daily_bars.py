"""Advance the resumable FinMind historical landing queue by one safe batch."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date
import json
import os
from pathlib import Path
import sys
from typing import cast
from uuid import uuid4

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root  # pyright: ignore[reportImplicitRelativeImport]

add_project_root()

from src.data.ingestion.contracts import IngestionError  # noqa: E402
from src.data.ingestion.historical_archive_repository import (  # noqa: E402
    HistoricalArchiveRepository,
)
from src.data.ingestion.historical_backfill_coordinator import (  # noqa: E402
    HistoricalBackfillCoordinator,
)
from src.data.ingestion.historical_backfill_repository import (  # noqa: E402
    HistoricalBackfillRepository,
)
from src.data.ingestion.historical_backfill_settings import (  # noqa: E402
    HistoricalBackfillSettings,
)
from src.data.ingestion.historical_daily_bar_archive_service import (  # noqa: E402
    HistoricalDailyBarArchiveService,
)
from src.data.ingestion.historical_daily_bar_landing_service import (  # noqa: E402
    HistoricalDailyBarLandingService,
)
from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402
from src.data.object_storage.r2_client import R2Client  # noqa: E402
from src.data.providers.errors import ProviderError  # noqa: E402
from src.data.providers.finmind import FinMindClient  # noqa: E402
from src.data.providers.settings import ApiProviderSettings  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Advance the research-only historical daily-bar queue."
    )
    _ = parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    _ = parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    _ = parser.add_argument("--max-tasks", type=int, default=60)
    _ = parser.add_argument("--output", type=Path, required=True)
    return parser


def _write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _worker_id() -> str:
    run_id = os.environ.get("GITHUB_RUN_ID", "local").strip() or "local"
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1").strip() or "1"
    return f"github-{run_id}-{attempt}-{uuid4().hex[:12]}"


def build_archive_service(
    *,
    settings: HistoricalBackfillSettings,
    writer: SupabaseWriter,
) -> HistoricalDailyBarArchiveService | None:
    if settings.storage_target != "R2":
        return None
    return HistoricalDailyBarArchiveService(
        store=R2Client.from_env(),
        repository=HistoricalArchiveRepository(writer),
        max_object_bytes=settings.max_archive_object_bytes,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = cast(Path, args.output)
    try:
        provider_settings = ApiProviderSettings.from_env()
        runtime_settings = HistoricalBackfillSettings.from_env()
        provider = FinMindClient(token=provider_settings.finmind_token)
        writer = SupabaseWriter(
            url=provider_settings.supabase_url,
            server_key=provider_settings.supabase_service_role_key,
            timeout=max(provider_settings.timeout_seconds, 30.0),
        )
        archive_service = build_archive_service(
            settings=runtime_settings,
            writer=writer,
        )
        summary = HistoricalBackfillCoordinator(
            provider=provider,
            repository=HistoricalBackfillRepository(writer),
            landing_service=HistoricalDailyBarLandingService(
                provider=provider,
                writer=writer,
                archive_service=archive_service,
            ),
            settings=runtime_settings,
        ).run(
            start_date=cast(date, args.start_date),
            end_date=cast(date, args.end_date),
            max_tasks=cast(int, args.max_tasks),
            worker_id=_worker_id(),
        )
        result = summary.to_dict()
        _write(output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (IngestionError, ProviderError, KeyError, TypeError, ValueError) as error:
        result: dict[str, object] = {
            "system_status": "FAIL",
            "outcome": "RUN_FAILED",
            "reason_code": getattr(
                error, "reason_code", "BACKFILL_CONFIGURATION_ERROR"
            ),
            "message": str(error),
        }
        _write(output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
