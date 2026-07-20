"""Normalize official TPEx English monthly price-index OHLC responses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from typing import cast
from urllib.parse import parse_qs, urlsplit

from src.data.providers.contracts import ProviderPayload
from src.data.providers.tpex import (
    TPEX_MONTHLY_OHLC_DATASET,
    TPEX_MONTHLY_OHLC_SOURCE_VERSION,
)

from .contracts import IngestionError
from .tpex_ohlc_contracts import (
    TPEX_OHLC_FIELDS,
    NormalizedTpexOhlcBatch,
    TpexOhlcObservation,
)


_RESPONSE_DATE_PATTERN = re.compile(r"^[0-9]{8}$")
_TABLE_MONTH_PATTERN = re.compile(r"^[0-9]{4}/[0-9]{2}$")
_TRADE_DATE_PATTERN = re.compile(r"^[0-9]{4}/[0-9]{2}/[0-9]{2}$")


def _fail(reason_code: str, message: str) -> IngestionError:
    return IngestionError(reason_code, message)


def _canonical_hash(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise _fail(
            "TPEX_OHLC_SOURCE_ROW_INVALID",
            "TPEx source row is not canonical JSON",
        ) from error
    return sha256(encoded).hexdigest()


def _requested_month(payload: ProviderPayload) -> date:
    metadata = payload.request_metadata
    if (
        metadata.get("calendar") != "GREGORIAN"
        or metadata.get("language") != "en"
        or metadata.get("available_at_policy") != "first_project_retrieval_only"
    ):
        raise _fail(
            "TPEX_OHLC_REQUEST_METADATA_INVALID",
            "TPEx OHLC request must use the Gregorian English endpoint",
        )
    value = metadata.get("requested_month")
    if not isinstance(value, str):
        raise _fail(
            "TPEX_OHLC_REQUEST_MONTH_INVALID",
            "TPEx OHLC request month is missing",
        )
    try:
        requested_month = date.fromisoformat(f"{value}-01")
    except ValueError as error:
        raise _fail(
            "TPEX_OHLC_REQUEST_MONTH_INVALID",
            "TPEx OHLC request month must use Gregorian YYYY-MM",
        ) from error
    request_date = requested_month.strftime("%Y/%m/01")
    if metadata.get("request_date") != request_date:
        raise _fail(
            "TPEX_OHLC_REQUEST_MONTH_INVALID",
            "TPEx request date does not match the requested month",
        )
    source = urlsplit(payload.source_url)
    if (
        source.scheme != "https"
        or source.hostname != "www.tpex.org.tw"
        or source.port is not None
        or source.username is not None
        or source.password is not None
        or source.path != "/www/en-us/indexInfo/inx"
        or source.fragment
        or parse_qs(source.query) != {"date": [request_date], "response": ["json"]}
    ):
        raise _fail(
            "TPEX_OHLC_SOURCE_URL_INVALID",
            "TPEx OHLC provenance does not identify the official monthly request",
        )
    return requested_month


def _response_date(raw: object, expected: date) -> date:
    if not isinstance(raw, str) or not _RESPONSE_DATE_PATTERN.fullmatch(raw):
        raise _fail(
            "TPEX_OHLC_RESPONSE_MONTH_INVALID",
            "TPEx response date must use Gregorian YYYYMMDD",
        )
    try:
        parsed = datetime.strptime(raw, "%Y%m%d").date()
    except ValueError as error:
        raise _fail(
            "TPEX_OHLC_RESPONSE_MONTH_INVALID",
            "TPEx response date must be a valid Gregorian date",
        ) from error
    if parsed.day != 1 or parsed != expected:
        raise _fail(
            "TPEX_OHLC_RESPONSE_MONTH_MISMATCH",
            "TPEx response month does not match the requested month",
        )
    return parsed


def _table_month(raw: object, expected: date) -> None:
    if not isinstance(raw, str) or not _TABLE_MONTH_PATTERN.fullmatch(raw):
        raise _fail(
            "TPEX_OHLC_TABLE_MONTH_INVALID",
            "TPEx table month must use Gregorian YYYY/MM",
        )
    try:
        parsed = datetime.strptime(raw, "%Y/%m").date()
    except ValueError as error:
        raise _fail(
            "TPEX_OHLC_TABLE_MONTH_INVALID",
            "TPEx table month must be a valid Gregorian month",
        ) from error
    if parsed != expected:
        raise _fail(
            "TPEX_OHLC_TABLE_MONTH_MISMATCH",
            "TPEx table month does not match the requested month",
        )


def _trade_date(raw: object, expected_month: date) -> date:
    if not isinstance(raw, str) or not _TRADE_DATE_PATTERN.fullmatch(raw.strip()):
        raise _fail(
            "TPEX_OHLC_TRADE_DATE_INVALID",
            "TPEx trade date must use Gregorian YYYY/MM/DD",
        )
    try:
        parsed = datetime.strptime(raw.strip(), "%Y/%m/%d").date()
    except ValueError as error:
        raise _fail(
            "TPEX_OHLC_TRADE_DATE_INVALID",
            "TPEx trade date must be a valid Gregorian date",
        ) from error
    if (parsed.year, parsed.month) != (expected_month.year, expected_month.month):
        raise _fail(
            "TPEX_OHLC_TRADE_DATE_OUTSIDE_MONTH",
            "TPEx trade date is outside the requested month",
        )
    return parsed


def _positive_decimal(raw: object, *, field: str) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float, Decimal)):
        raise _fail(
            "TPEX_OHLC_VALUE_INVALID",
            f"TPEx {field} must be a finite positive number",
        )
    try:
        value = Decimal(str(raw).replace(",", "").strip())
    except InvalidOperation as error:
        raise _fail(
            "TPEX_OHLC_VALUE_INVALID",
            f"TPEx {field} must be a finite positive number",
        ) from error
    if not value.is_finite() or value <= 0:
        raise _fail(
            "TPEX_OHLC_VALUE_INVALID",
            f"TPEx {field} must be a finite positive number",
        )
    return value


def _observation(
    raw: object, *, row_index: int, requested_month: date
) -> TpexOhlcObservation:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise _fail("TPEX_OHLC_ROW_INVALID", "TPEx OHLC row must be an array")
    values = raw
    if len(values) != len(TPEX_OHLC_FIELDS):
        raise _fail(
            "TPEX_OHLC_ROW_INVALID",
            "TPEx OHLC row does not match the six-field contract",
        )
    source_row = tuple(str(value) for value in values)
    trade_date = _trade_date(values[0], requested_month)
    open_index = _positive_decimal(values[1], field="open")
    high_index = _positive_decimal(values[2], field="high")
    low_index = _positive_decimal(values[3], field="low")
    close_index = _positive_decimal(values[4], field="close")
    if high_index < max(open_index, low_index, close_index):
        raise _fail(
            "TPEX_OHLC_HIGH_INVARIANT_FAILED",
            "TPEx high must be at least open, low, and close",
        )
    if low_index > min(open_index, high_index, close_index):
        raise _fail(
            "TPEX_OHLC_LOW_INVARIANT_FAILED",
            "TPEx low must be at most open, high, and close",
        )
    source_revision_hash = _canonical_hash(
        {
            "provider": "TPEX",
            "dataset": TPEX_MONTHLY_OHLC_DATASET,
            "row": list(values),
        }
    )
    landing_key = _canonical_hash(
        {
            "provider": "TPEX",
            "dataset": TPEX_MONTHLY_OHLC_DATASET,
            "trade_date": trade_date.isoformat(),
            "source_revision_hash": source_revision_hash,
        }
    )
    return TpexOhlcObservation(
        source_row_index=row_index,
        source_row=cast(tuple[str, str, str, str, str, str], source_row),
        landing_key=landing_key,
        source_revision_hash=source_revision_hash,
        trade_date=trade_date,
        open_index=open_index,
        high_index=high_index,
        low_index=low_index,
        close_index=close_index,
    )


def _table(body: Mapping[str, object]) -> Mapping[str, object]:
    raw_tables = body.get("tables")
    tables = cast(list[object], raw_tables) if isinstance(raw_tables, list) else None
    if tables is None or len(tables) != 1:
        raise _fail(
            "TPEX_OHLC_TABLES_INVALID",
            "TPEx response must contain exactly one index table",
        )
    raw_table = tables[0]
    if not isinstance(raw_table, Mapping):
        raise _fail(
            "TPEX_OHLC_TABLES_INVALID",
            "TPEx index table must be an object",
        )
    return cast(Mapping[str, object], raw_table)


def normalize_tpex_monthly_ohlc(payload: ProviderPayload) -> NormalizedTpexOhlcBatch:
    """Fail closed unless one complete official TPEx monthly payload is valid."""

    if (
        payload.provider != "TPEX"
        or payload.dataset != TPEX_MONTHLY_OHLC_DATASET
        or payload.source_version != TPEX_MONTHLY_OHLC_SOURCE_VERSION
    ):
        raise _fail(
            "TPEX_OHLC_SOURCE_INVALID",
            "only the official TPEx English monthly index source is accepted",
        )
    raw_payload = cast(object, payload.payload)
    if not isinstance(raw_payload, Mapping):
        raise _fail("TPEX_OHLC_PAYLOAD_INVALID", "TPEx payload must be an object")
    body = cast(Mapping[str, object], raw_payload)
    if body.get("stat") != "ok":
        raise _fail(
            "TPEX_OHLC_STAT_NOT_OK",
            "TPEx provider response did not report ok",
        )
    requested_month = _requested_month(payload)
    response_date = _response_date(body.get("date"), requested_month)
    table = _table(body)
    _table_month(table.get("date"), requested_month)
    raw_fields = table.get("fields")
    fields = cast(list[object], raw_fields) if isinstance(raw_fields, list) else None
    if fields is None or tuple(fields) != TPEX_OHLC_FIELDS:
        raise _fail(
            "TPEX_OHLC_FIELDS_MISMATCH",
            "TPEx response fields do not match the OHLC contract",
        )
    raw_data = table.get("data")
    raw_rows = cast(list[object], raw_data) if isinstance(raw_data, list) else None
    if not raw_rows:
        raise _fail(
            "TPEX_OHLC_DATA_EMPTY",
            "TPEx response must contain at least one OHLC row",
        )
    total_count = table.get("totalCount")
    if (
        isinstance(total_count, bool)
        or not isinstance(total_count, int)
        or total_count != len(raw_rows)
    ):
        raise _fail(
            "TPEX_OHLC_TOTAL_COUNT_MISMATCH",
            "TPEx totalCount must equal the number of source rows",
        )
    rows = tuple(
        _observation(raw, row_index=index, requested_month=requested_month)
        for index, raw in enumerate(raw_rows)
    )
    dates = [row.trade_date for row in rows]
    if len(dates) != len(set(dates)):
        raise _fail(
            "TPEX_OHLC_DUPLICATE_TRADE_DATE",
            "TPEx response contains duplicate trade dates",
        )
    if dates != sorted(dates):
        raise _fail(
            "TPEX_OHLC_TRADE_DATES_NOT_ASCENDING",
            "TPEx response trade dates must be strictly ascending",
        )
    return NormalizedTpexOhlcBatch(
        requested_month=requested_month,
        response_date=response_date,
        source_version=payload.source_version,
        source_url=payload.source_url,
        source_payload_sha256=payload.payload_sha256,
        retrieved_at=payload.retrieved_at,
        available_at=payload.retrieved_at,
        rows=rows,
    )
