"""Archive bounded official TAIEX monthly OHLC tasks to private R2."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import sys
from typing import cast
from uuid import uuid4
from zoneinfo import ZoneInfo

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
from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402
from src.data.ingestion.taiex_ohlc_archive_service import (  # noqa: E402
    TaiexOhlcArchiveService,
)
from src.data.ingestion.taiex_ohlc_backfill_coordinator import (  # noqa: E402
    TaiexOhlcBackfillCoordinator,
)
from src.data.ingestion.taiex_ohlc_backfill_repository import (  # noqa: E402
    TaiexOhlcBackfillRepository,
)
from src.data.ingestion.taiex_ohlc_landing_service import (  # noqa: E402
    TaiexOhlcLandingService,
)
from src.data.object_storage.r2_client import R2Client  # noqa: E402
from src.data.providers.errors import ProviderError  # noqa: E402
from src.data.providers.http import JsonHttpClient  # noqa: E402
from src.data.providers.settings import ApiProviderSettings  # noqa: E402
from src.data.providers.twse import TwseClient  # noqa: E402


TAIPEI = ZoneInfo("Asia/Taipei")


def _month(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "month must use Gregorian YYYY-MM-01"
        ) from error
    if parsed.day != 1:
        raise argparse.ArgumentTypeError("month must be the first calendar day")
    return parsed


def _previous_month() -> date:
    current = datetime.now(TAIPEI).date().replace(day=1)
    return (current - timedelta(days=1)).replace(day=1)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Archive completed official TAIEX monthly OHLC responses."
    )
    _ = parser.add_argument(
        "--start-month",
        type=_month,
        default=date(2018, 1, 1),
    )
    _ = parser.add_argument("--end-month", type=_month, default=_previous_month())
    _ = parser.add_argument("--max-tasks", type=int, default=24)
    _ = parser.add_argument("--request-interval-seconds", type=float, default=1.0)
    _ = parser.add_argument("--output", type=Path, required=True)
    return parser


def _worker_id() -> str:
    run_id = os.environ.get("GITHUB_RUN_ID", "local").strip() or "local"
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1").strip() or "1"
    return f"taiex-ohlc-{run_id}-{attempt}-{uuid4().hex[:12]}"


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
        if runtime_settings.storage_target != "R2":
            raise ValueError("HISTORICAL_BACKFILL_STORAGE_TARGET must be R2")
        writer = SupabaseWriter(
            url=provider_settings.supabase_url,
            server_key=provider_settings.supabase_service_role_key,
            timeout=max(provider_settings.timeout_seconds, 30.0),
        )
        store = R2Client.from_env()
        summary = TaiexOhlcBackfillCoordinator(
            repository=TaiexOhlcBackfillRepository(writer),
            landing_service=TaiexOhlcLandingService(
                provider=TwseClient(
                    http=JsonHttpClient(
                        timeout=provider_settings.timeout_seconds,
                        max_attempts=3,
                        retry_backoff_seconds=1.0,
                    )
                ),
                archive_service=TaiexOhlcArchiveService(
                    store=store,
                    repository=HistoricalArchiveRepository(writer),
                    max_object_bytes=runtime_settings.max_archive_object_bytes,
                ),
            ),
        ).run(
            start_month=cast(date, args.start_month),
            end_month=cast(date, args.end_month),
            worker_id=_worker_id(),
            max_tasks=cast(int, args.max_tasks),
            request_interval_seconds=cast(float, args.request_interval_seconds),
            lease_seconds=min(runtime_settings.lease_seconds, 1800),
            retry_after_seconds=runtime_settings.retry_after_seconds,
        )
        result = summary.to_dict()
        _write(output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if summary.outcome == "BLOCKED" else 0
    except (IngestionError, ProviderError, KeyError, TypeError, ValueError) as error:
        result: dict[str, object] = {
            "system_status": "FAIL",
            "outcome": "RUN_FAILED",
            "benchmark_semantics": "PRICE_INDEX_NOT_TOTAL_RETURN",
            "usage_scope": "RAW_LANDING_ONLY",
            "reason_code": getattr(
                error,
                "reason_code",
                "TAIEX_OHLC_BACKFILL_CONFIGURATION_ERROR",
            ),
            "message": str(error),
        }
        _write(output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
