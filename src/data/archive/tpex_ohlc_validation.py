"""Dataset-specific semantic validation for archived TPEx OHLC rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from calendar import monthrange
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from typing import cast

from src.data.ingestion.tpex_ohlc_contracts import TPEX_OHLC_SYMBOL
from src.data.providers.tpex import TPEX_MONTHLY_OHLC_DATASET

from .contracts import HistoricalArchiveManifest, HistoricalArchiveReadError


def _fail(message: str) -> HistoricalArchiveReadError:
    return HistoricalArchiveReadError("TPEX_OHLC_ARCHIVE_INVALID", message)


def _positive_decimal(row: Mapping[str, object], field: str) -> Decimal:
    value = row.get(field)
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise _fail(f"Archived TPEx {field} is not finite and positive")
    return value


def _source_row(value: object) -> tuple[str, str, str, str, str, str]:
    try:
        parsed = cast(object, json.loads(str(value)))
    except (TypeError, ValueError) as error:
        raise _fail("Archived TPEx source row is not valid JSON") from error
    values = cast(list[object], parsed) if isinstance(parsed, list) else None
    if (
        values is None
        or len(values) != 6
        or any(not isinstance(item, str) for item in values)
    ):
        raise _fail("Archived TPEx source row does not preserve six string fields")
    strings = cast(list[str], values)
    return (
        strings[0],
        strings[1],
        strings[2],
        strings[3],
        strings[4],
        strings[5],
    )


def _source_decimal(value: str, *, field: str) -> Decimal:
    try:
        parsed = Decimal(value.replace(",", "").strip())
    except InvalidOperation as error:
        raise _fail(f"Archived TPEx source {field} is invalid") from error
    if not parsed.is_finite() or parsed <= 0:
        raise _fail(f"Archived TPEx source {field} is invalid")
    return parsed


def validate_tpex_ohlc_rows(
    rows: Sequence[Mapping[str, object]],
    manifest: HistoricalArchiveManifest,
) -> None:
    """Reject structurally valid Parquet with invalid index semantics."""

    if (
        manifest.provider_code != "TPEX"
        or manifest.source_dataset != TPEX_MONTHLY_OHLC_DATASET
        or manifest.scheduled_market != "TPEX"
        or manifest.asset_type != "BENCHMARK"
        or manifest.source_symbol != TPEX_OHLC_SYMBOL
        or manifest.requested_start_date.day != 1
        or manifest.requested_end_date
        != manifest.requested_start_date.replace(
            day=monthrange(
                manifest.requested_start_date.year,
                manifest.requested_start_date.month,
            )[1]
        )
    ):
        raise _fail("TPEx OHLC manifest scope is invalid")
    trade_dates: list[date] = []
    for row in rows:
        trade_date = row.get("trade_date")
        if type(trade_date) is not date:
            raise _fail("Archived TPEx row is missing its trade date")
        try:
            raw_reason_codes = cast(object, json.loads(str(row.get("reason_codes"))))
            quarantine_issues = cast(
                object, json.loads(str(row.get("quarantine_issues")))
            )
        except (TypeError, ValueError) as error:
            raise _fail("Archived TPEx row metadata is not valid JSON") from error
        if not isinstance(raw_reason_codes, list):
            raise _fail("Archived TPEx reason codes are invalid")
        reason_values = cast(list[object], raw_reason_codes)
        if any(not isinstance(code, str) or not code for code in reason_values):
            raise _fail("Archived TPEx reason codes are invalid")
        reason_codes = tuple(cast(str, code) for code in reason_values)
        source_row = _source_row(row.get("source_row"))
        if (
            row.get("requested_month") != manifest.requested_start_date
            or row.get("response_date") != manifest.requested_start_date
            or row.get("source_trade_date") != trade_date.isoformat()
            or source_row[0] != trade_date.strftime("%Y/%m/%d")
            or row.get("benchmark_semantics") != "PRICE_INDEX_NOT_TOTAL_RETURN"
            or row.get("available_at_basis") != "FIRST_OBSERVED_AT_RETRIEVAL"
            or row.get("parse_status") != "PARSED"
            or row.get("available_at") != manifest.first_observed_at
            or reason_codes != manifest.reason_codes
            or quarantine_issues != []
        ):
            raise _fail("Archived TPEx row provenance or semantics are invalid")
        open_index = _positive_decimal(row, "open_index")
        high_index = _positive_decimal(row, "high_index")
        low_index = _positive_decimal(row, "low_index")
        close_index = _positive_decimal(row, "close_index")
        if (
            _source_decimal(source_row[1], field="open") != open_index
            or _source_decimal(source_row[2], field="high") != high_index
            or _source_decimal(source_row[3], field="low") != low_index
            or _source_decimal(source_row[4], field="close") != close_index
        ):
            raise _fail("Archived TPEx parsed OHLC differs from its raw source row")
        if high_index < max(open_index, low_index, close_index):
            raise _fail("Archived TPEx high index violates the OHLC invariant")
        if low_index > min(open_index, high_index, close_index):
            raise _fail("Archived TPEx low index violates the OHLC invariant")
        trade_dates.append(trade_date)
    if trade_dates != sorted(trade_dates) or len(trade_dates) != len(set(trade_dates)):
        raise _fail("Archived TPEx trade dates are not unique and ascending")
