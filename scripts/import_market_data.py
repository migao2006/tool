"""Import the first auditable ordinary-stock snapshot into Supabase."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import date
import json
from pathlib import Path
import re
import sys
from typing import Sequence, cast

try:
    from scripts._bootstrap import add_project_root
except ModuleNotFoundError:
    from _bootstrap import add_project_root

add_project_root()

from src.data.ingestion.contracts import IngestionError  # noqa: E402
from src.data.ingestion.daily_import import DailyMarketImporter  # noqa: E402
from src.data.providers.errors import ProviderError  # noqa: E402
from src.data.providers.settings import ApiProviderSettings  # noqa: E402


TRANSIENT_SOURCE_EXIT_CODE = 75
TRANSIENT_SOURCE_REASON_CODES = frozenset({"SOURCE_MARKET_DATE_MISMATCH"})
_SAFE_REASON_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import audited Taiwan market data.")
    parser.add_argument("--as-of-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--result-output", type=Path)
    return parser


def _safe_reason_code(value: object) -> str:
    rendered = str(value)
    return rendered if _SAFE_REASON_CODE.fullmatch(rendered) else "IMPORT_FAILED"


def _safe_iso_date(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return value if parsed.isoformat() == value else None


def _write_recovery_result(
    path: Path | None,
    *,
    status: str,
    reason_code: object,
    requested_as_of_date: date,
    as_of_date: object | None = None,
    source_dates: Mapping[str, object] | None = None,
) -> None:
    if path is None:
        return
    payload: dict[str, object] = {
        "schema_version": 1,
        "status": status,
        "reason_code": _safe_reason_code(reason_code),
        "requested_as_of_date": requested_as_of_date.isoformat(),
    }
    safe_as_of_date = _safe_iso_date(as_of_date)
    if safe_as_of_date is not None:
        payload["as_of_date"] = safe_as_of_date
    for market, field in (
        ("TWSE", "twse_source_date"),
        ("TPEX", "tpex_source_date"),
    ):
        safe_source_date = _safe_iso_date((source_dates or {}).get(market))
        if safe_source_date is not None:
            payload[field] = safe_source_date
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result_output = cast(Path | None, args.result_output)
    try:
        summary = DailyMarketImporter(settings=ApiProviderSettings.from_env()).run(
            as_of_date=args.as_of_date,
            dry_run=args.dry_run,
        )
        print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        _write_recovery_result(
            result_output,
            status="PASS",
            reason_code="IMPORT_COMPLETED",
            requested_as_of_date=args.as_of_date,
            as_of_date=summary.as_of_date.isoformat(),
            source_dates=summary.source_dates,
        )
        return 0
    except (IngestionError, ProviderError, KeyError, ValueError) as error:
        reason_code = getattr(error, "reason_code", "IMPORT_CONFIGURATION_ERROR")
        is_transient = reason_code in TRANSIENT_SOURCE_REASON_CODES
        payload: dict[str, object] = {
            "status": "DEFERRED" if is_transient else "FAIL",
            "reason_code": reason_code,
            "message": str(error),
        }
        context = getattr(error, "context", None)
        if isinstance(context, dict) and context:
            payload["context"] = context
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        recovery_source_dates: dict[str, object] = {}
        if isinstance(context, Mapping):
            recovery_source_dates = {
                "TWSE": context.get("twse_source_date"),
                "TPEX": context.get("tpex_source_date"),
            }
        _write_recovery_result(
            result_output,
            status="DEFERRED" if is_transient else "FAIL",
            reason_code=reason_code,
            requested_as_of_date=args.as_of_date,
            source_dates=recovery_source_dates,
        )
        if is_transient:
            return TRANSIENT_SOURCE_EXIT_CODE
        return 1


if __name__ == "__main__":
    sys.exit(main())
