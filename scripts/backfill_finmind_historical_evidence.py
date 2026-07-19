"""Run one quota-bounded TWSE company-action/state evidence batch."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date, datetime
import json
from pathlib import Path
import sys
from typing import cast
from zoneinfo import ZoneInfo

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root  # pyright: ignore[reportImplicitRelativeImport]

add_project_root()

from src.data.ingestion.contracts import IngestionError  # noqa: E402
from src.data.ingestion.finmind_historical_evidence_import import (  # noqa: E402
    FinMindHistoricalEvidenceImporter,
)
from src.data.ingestion.finmind_historical_evidence_schedule import (  # noqa: E402
    select_symbol_batch,
)
from src.data.ingestion.finmind_historical_identity import (  # noqa: E402
    load_all_verified_twse_identities,
)
from src.data.ingestion.supabase_writer import SupabaseWriter  # noqa: E402
from src.data.providers.errors import ProviderError  # noqa: E402
from src.data.providers.settings import ApiProviderSettings  # noqa: E402


TAIPEI = ZoneInfo("Asia/Taipei")
CREDENTIAL_SLOTS = ("primary", "secondary", "tertiary")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill TWSE FinMind action and suspension research evidence."
    )
    _ = parser.add_argument(
        "--start-date", type=date.fromisoformat, default=date(2000, 1, 1)
    )
    _ = parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=datetime.now(TAIPEI).date(),
    )
    _ = parser.add_argument("--shard-index", type=int, required=True)
    _ = parser.add_argument("--shard-count", type=int, default=3)
    _ = parser.add_argument("--batch-index", type=int, required=True)
    _ = parser.add_argument("--max-symbols", type=int, default=12)
    _ = parser.add_argument("--pacing-seconds", type=float, default=7.5)
    _ = parser.add_argument("--quota-reserve", type=int, default=30)
    _ = parser.add_argument(
        "--credential-slot", choices=CREDENTIAL_SLOTS, required=True
    )
    _ = parser.add_argument("--include-global", action="store_true")
    _ = parser.add_argument("--dry-run", action="store_true")
    _ = parser.add_argument("--defer-on-quota", action="store_true")
    _ = parser.add_argument("--output", type=Path, required=True)
    return parser


def _write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _failure(error: Exception) -> dict[str, object]:
    return {
        "system_status": "FAIL",
        "usage_scope": "HISTORICAL_EVIDENCE_RESEARCH_ONLY",
        "outcome": "RUN_FAILED",
        "reason_code": getattr(
            error, "reason_code", "FINMIND_HISTORICAL_EVIDENCE_CONFIGURATION_ERROR"
        ),
        "message": str(error),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = cast(Path, args.output)
    try:
        settings = ApiProviderSettings.from_env()
        writer = SupabaseWriter(
            url=settings.supabase_url,
            server_key=settings.supabase_service_role_key,
            timeout=max(settings.timeout_seconds, 30.0),
        )
        identities = load_all_verified_twse_identities(writer)
        symbols = select_symbol_batch(
            identities,
            shard_index=cast(int, args.shard_index),
            shard_count=cast(int, args.shard_count),
            batch_index=cast(int, args.batch_index),
            max_symbols=cast(int, args.max_symbols),
        )
        summary = FinMindHistoricalEvidenceImporter(
            settings=settings,
            writer=writer,
        ).run(
            symbols=symbols,
            start_date=cast(date, args.start_date),
            end_date=cast(date, args.end_date),
            pacing_seconds=cast(float, args.pacing_seconds),
            scope="ALL" if cast(bool, args.include_global) else "DIVIDENDS",
            quota_reserve=cast(int, args.quota_reserve),
            dry_run=cast(bool, args.dry_run),
            identities=identities,
            global_symbols=(
                tuple(sorted({item.source_symbol for item in identities}))
                if cast(bool, args.include_global)
                else None
            ),
        )
        result = {
            **summary.to_dict(),
            "outcome": "BATCH_COMPLETED",
            "credential_slot": cast(str, args.credential_slot),
            "shard_index": cast(int, args.shard_index),
            "shard_count": cast(int, args.shard_count),
            "batch_index": cast(int, args.batch_index),
        }
        _write(output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (IngestionError, ProviderError, KeyError, TypeError, ValueError) as error:
        result = _failure(error)
        if (
            cast(bool, args.defer_on_quota)
            and result["reason_code"] == "FINMIND_HISTORICAL_QUOTA_INSUFFICIENT"
        ):
            result.update(
                {
                    "system_status": "RESEARCH_ONLY",
                    "outcome": "DEFERRED_QUOTA",
                    "credential_slot": cast(str, args.credential_slot),
                }
            )
            _write(output, result)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        _write(output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
