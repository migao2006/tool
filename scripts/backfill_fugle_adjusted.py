"""Advance the isolated Fugle adjusted TWSE archive queue."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
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
from src.data.ingestion.historical_fugle_adjusted_backfill_contracts import (  # noqa: E402
    FugleAdjustedBackfillSettings,
)
from src.data.ingestion.historical_fugle_adjusted_backfill_coordinator import (  # noqa: E402
    FugleAdjustedBackfillCoordinator,
)
from src.data.ingestion.historical_fugle_adjusted_backfill_repository import (  # noqa: E402
    FugleAdjustedBackfillRepository,
)
from src.data.ingestion.historical_fugle_adjusted_provider import (  # noqa: E402
    FugleAdjustedBackfillProvider,
)
from src.data.ingestion.historical_supplemental_landing_service import (  # noqa: E402
    HistoricalSupplementalLandingService,
)
from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402
from src.data.object_storage.r2_client import R2Client  # noqa: E402
from src.data.providers.errors import ProviderError  # noqa: E402
from src.data.providers.fugle import FugleClient  # noqa: E402
from src.data.providers.http import JsonHttpClient  # noqa: E402
from src.data.providers.settings import ApiProviderSettings  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Advance research-only Fugle adjusted TWSE history."
    )
    _ = parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    _ = parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    _ = parser.add_argument("--max-tasks", type=int, default=25)
    _ = parser.add_argument("--output", type=Path, required=True)
    return parser


def _worker_id() -> str:
    run_id = os.environ.get("GITHUB_RUN_ID", "local").strip() or "local"
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1").strip() or "1"
    return f"fugle-adjusted-{run_id}-{attempt}-{uuid4().hex[:12]}"


def _write(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _disabled_result() -> dict[str, object]:
    return {
        "outcome": "DISABLED",
        "system_status": "RESEARCH_ONLY",
        "usage_scope": "RAW_LANDING_ONLY",
        "attempted_tasks": 0,
        "reason_codes": ["FUGLE_ADJUSTED_BACKFILL_FEATURE_DISABLED"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = cast(Path, args.output)
    fugle_settings = FugleAdjustedBackfillSettings.from_env()
    if not fugle_settings.enabled:
        result = _disabled_result()
        _write(output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    try:
        provider_settings = ApiProviderSettings.from_env()
        runtime_settings = HistoricalBackfillSettings.from_env()
        if runtime_settings.storage_target != "R2":
            raise ValueError("HISTORICAL_BACKFILL_STORAGE_TARGET must be R2")
        writer = SupabaseWriter(
            url=provider_settings.supabase_url,
            server_key=provider_settings.supabase_service_role_key,
            timeout=max(provider_settings.timeout_seconds, 30.0),
        )
        repository = FugleAdjustedBackfillRepository(writer)
        # The dedicated RPC exists only after the migration is deployed. Fail
        # here before constructing an R2 client or calling Fugle.
        _ = repository.ensure_contract_available(
            start_date=cast(date, args.start_date),
            end_date=cast(date, args.end_date),
        )
        provider = FugleAdjustedBackfillProvider(
            FugleClient(
                api_key=provider_settings.fugle_api_key,
                http=JsonHttpClient(
                    timeout=provider_settings.timeout_seconds,
                    max_attempts=1,
                    retry_backoff_seconds=0.0,
                ),
            )
        )
        archive_service = HistoricalDailyBarArchiveService(
            store=R2Client.from_env(),
            repository=HistoricalArchiveRepository(writer),
            max_object_bytes=runtime_settings.max_archive_object_bytes,
        )
        summary = FugleAdjustedBackfillCoordinator(
            repository=repository,
            landing_service=HistoricalSupplementalLandingService(
                provider=provider,
                archive_service=archive_service,
            ),
            runtime_settings=runtime_settings,
            fugle_settings=fugle_settings,
        ).run(
            start_date=cast(date, args.start_date),
            end_date=cast(date, args.end_date),
            max_tasks=cast(int, args.max_tasks),
            worker_id=_worker_id(),
        )
        result = summary.to_dict()
        _write(output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if summary.outcome == "EXHAUSTED_TASKS" else 0
    except (IngestionError, ProviderError, KeyError, TypeError, ValueError) as error:
        raw_reason_code = getattr(error, "reason_code", None)
        reason_code = (
            raw_reason_code
            if isinstance(raw_reason_code, str)
            else "FUGLE_ADJUSTED_BACKFILL_CONFIGURATION_ERROR"
        )
        result: dict[str, object] = {
            "system_status": "FAIL",
            "outcome": "RUN_FAILED",
            "reason_code": reason_code,
            "message": str(error),
        }
        _write(output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
