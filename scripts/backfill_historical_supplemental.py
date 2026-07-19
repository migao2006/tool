"""Advance the TWSE FinMind supplemental-history queue by one bounded batch."""

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
from src.data.ingestion.historical_backfill_settings import (  # noqa: E402
    HistoricalBackfillSettings,
)
from src.data.ingestion.historical_daily_bar_archive_service import (  # noqa: E402
    HistoricalDailyBarArchiveService,
)
from src.data.ingestion.historical_supplemental_backfill_coordinator import (  # noqa: E402
    HistoricalSupplementalBackfillCoordinator,
)
from src.data.ingestion.historical_supplemental_backfill_repository import (  # noqa: E402
    HistoricalSupplementalBackfillRepository,
)
from src.data.ingestion.historical_supplemental_backfill_settings import (  # noqa: E402
    HistoricalSupplementalBackfillSettings,
)
from src.data.ingestion.historical_supplemental_landing_service import (  # noqa: E402
    HistoricalSupplementalLandingService,
)
from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402
from src.data.object_storage.r2_client import R2Client  # noqa: E402
from src.data.providers.errors import ProviderError  # noqa: E402
from src.data.providers.finmind import FinMindClient  # noqa: E402
from src.data.providers.settings import ApiProviderSettings  # noqa: E402


_FAILED_OUTCOMES = frozenset({"EXHAUSTED_TASKS"})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Advance TWSE adjusted, institutional, and margin history."
    )
    _ = parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    _ = parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    _ = parser.add_argument("--max-tasks", type=int, default=100)
    _ = parser.add_argument("--output", type=Path, required=True)
    return parser


def _worker_id() -> str:
    run_id = os.environ.get("GITHUB_RUN_ID", "local").strip() or "local"
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1").strip() or "1"
    return f"supplemental-{run_id}-{attempt}-{uuid4().hex[:12]}"


def _write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = cast(Path, args.output)
    try:
        provider_settings = ApiProviderSettings.from_env()
        runtime_settings = HistoricalBackfillSettings.from_env()
        supplemental_settings = HistoricalSupplementalBackfillSettings.from_env()
        if runtime_settings.storage_target != "R2":
            raise ValueError("HISTORICAL_BACKFILL_STORAGE_TARGET must be R2")
        provider = FinMindClient(token=provider_settings.finmind_token)
        writer = SupabaseWriter(
            url=provider_settings.supabase_url,
            server_key=provider_settings.supabase_service_role_key,
            timeout=max(provider_settings.timeout_seconds, 30.0),
        )
        archive_service = HistoricalDailyBarArchiveService(
            store=R2Client.from_env(),
            repository=HistoricalArchiveRepository(writer),
            max_object_bytes=runtime_settings.max_archive_object_bytes,
        )
        summary = HistoricalSupplementalBackfillCoordinator(
            provider=provider,
            repository=HistoricalSupplementalBackfillRepository(writer),
            landing_service=HistoricalSupplementalLandingService(
                provider=provider,
                archive_service=archive_service,
            ),
            settings=runtime_settings,
            supplemental_settings=supplemental_settings,
        ).run(
            start_date=cast(date, args.start_date),
            end_date=cast(date, args.end_date),
            max_tasks=cast(int, args.max_tasks),
            worker_id=_worker_id(),
        )
        result = summary.to_dict()
        _write(output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if summary.outcome in _FAILED_OUTCOMES else 0
    except (IngestionError, ProviderError, KeyError, TypeError, ValueError) as error:
        result: dict[str, object] = {
            "system_status": "FAIL",
            "outcome": "RUN_FAILED",
            "reason_code": getattr(
                error, "reason_code", "SUPPLEMENTAL_BACKFILL_CONFIGURATION_ERROR"
            ),
            "message": str(error),
        }
        _write(output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
