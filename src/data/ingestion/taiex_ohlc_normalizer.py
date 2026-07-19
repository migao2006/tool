"""Normalize the official TWSE English TAIEX monthly OHLC response."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import cast
from urllib.parse import parse_qs, urlsplit

from src.data.providers.contracts import ProviderPayload
from src.data.providers.twse import (
    TAIEX_MONTHLY_OHLC_DATASET,
    TAIEX_MONTHLY_OHLC_SOURCE_VERSION,
)

from .contracts import IngestionError
from .taiex_ohlc_contracts import (
    TAIEX_OHLC_FIELDS,
    NormalizedTaiexOhlcBatch,
    TaiexOhlcObservation,
)


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
            "TAIEX_OHLC_SOURCE_ROW_INVALID",
            "TAIEX source row is not canonical JSON",
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
            "TAIEX_OHLC_REQUEST_METADATA_INVALID",
            "TAIEX OHLC request must use the Gregorian English endpoint",
        )
    value = metadata.get("requested_month")
    if not isinstance(value, str):
        raise _fail(
            "TAIEX_OHLC_REQUEST_MONTH_INVALID",
            "TAIEX OHLC request month is missing",
        )
    try:
        requested_month = date.fromisoformat(f"{value}-01")
    except ValueError as error:
        raise _fail(
            "TAIEX_OHLC_REQUEST_MONTH_INVALID",
            "TAIEX OHLC request month must use Gregorian YYYY-MM",
        ) from error
    request_date = requested_month.strftime("%Y%m%d")
    if metadata.get("request_date") != request_date:
        raise _fail(
            "TAIEX_OHLC_REQUEST_MONTH_INVALID",
            "TAIEX OHLC request date does not match the requested month",
        )
    source = urlsplit(payload.source_url)
    if (
        source.scheme != "https"
        or source.hostname != "www.twse.com.tw"
        or source.path != "/rwd/en/TAIEX/MI_5MINS_HIST"
        or parse_qs(source.query) != {"date": [request_date], "response": ["json"]}
    ):
        raise _fail(
            "TAIEX_OHLC_SOURCE_URL_INVALID",
            "TAIEX OHLC provenance does not identify the official monthly request",
        )
    return requested_month


def _response_month(raw: object, expected: date) -> date:
    if (
        not isinstance(raw, str)
        or len(raw) != 8
        or not raw.isascii()
        or not raw.isdigit()
    ):
        raise _fail(
            "TAIEX_OHLC_RESPONSE_MONTH_INVALID",
            "TAIEX response date must use Gregorian YYYYMMDD",
        )
    try:
        parsed = datetime.strptime(raw, "%Y%m%d").date()
    except ValueError as error:
        raise _fail(
            "TAIEX_OHLC_RESPONSE_MONTH_INVALID",
            "TAIEX response date must be a valid Gregorian date",
        ) from error
    if parsed.day != 1 or parsed != expected:
        raise _fail(
            "TAIEX_OHLC_RESPONSE_MONTH_MISMATCH",
            "TAIEX response month does not match the requested month",
        )
    return parsed


def _trade_date(raw: object, expected_month: date) -> date:
    if not isinstance(raw, str):
        raise _fail("TAIEX_OHLC_TRADE_DATE_INVALID", "TAIEX trade date is invalid")
    try:
        parsed = datetime.strptime(raw.strip(), "%Y/%m/%d").date()
    except ValueError as error:
        raise _fail(
            "TAIEX_OHLC_TRADE_DATE_INVALID",
            "TAIEX trade date must use Gregorian YYYY/MM/DD",
        ) from error
    if (parsed.year, parsed.month) != (expected_month.year, expected_month.month):
        raise _fail(
            "TAIEX_OHLC_TRADE_DATE_OUTSIDE_MONTH",
            "TAIEX trade date is outside the requested month",
        )
    return parsed


def _positive_decimal(raw: object, *, field: str) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float, Decimal)):
        raise _fail(
            "TAIEX_OHLC_VALUE_INVALID",
            f"TAIEX {field} must be a finite positive number",
        )
    try:
        value = Decimal(str(raw).replace(",", "").strip())
    except InvalidOperation as error:
        raise _fail(
            "TAIEX_OHLC_VALUE_INVALID",
            f"TAIEX {field} must be a finite positive number",
        ) from error
    if not value.is_finite() or value <= 0:
        raise _fail(
            "TAIEX_OHLC_VALUE_INVALID",
            f"TAIEX {field} must be a finite positive number",
        )
    return value


def _observation(
    raw: object, *, row_index: int, requested_month: date
) -> TaiexOhlcObservation:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise _fail("TAIEX_OHLC_ROW_INVALID", "TAIEX OHLC row must be an array")
    values = raw
    if len(values) != len(TAIEX_OHLC_FIELDS):
        raise _fail(
            "TAIEX_OHLC_ROW_INVALID",
            "TAIEX OHLC row does not match the five-field contract",
        )
    source_row = tuple(str(value) for value in values)
    trade_date = _trade_date(values[0], requested_month)
    open_index = _positive_decimal(values[1], field="open")
    high_index = _positive_decimal(values[2], field="high")
    low_index = _positive_decimal(values[3], field="low")
    close_index = _positive_decimal(values[4], field="close")
    if high_index < max(open_index, low_index, close_index):
        raise _fail(
            "TAIEX_OHLC_HIGH_INVARIANT_FAILED",
            "TAIEX high must be at least open, low, and close",
        )
    if low_index > min(open_index, high_index, close_index):
        raise _fail(
            "TAIEX_OHLC_LOW_INVARIANT_FAILED",
            "TAIEX low must be at most open, high, and close",
        )
    source_revision_hash = _canonical_hash(
        {
            "provider": "TWSE",
            "dataset": TAIEX_MONTHLY_OHLC_DATASET,
            "row": list(values),
        }
    )
    landing_key = _canonical_hash(
        {
            "provider": "TWSE",
            "dataset": TAIEX_MONTHLY_OHLC_DATASET,
            "trade_date": trade_date.isoformat(),
            "source_revision_hash": source_revision_hash,
        }
    )
    return TaiexOhlcObservation(
        source_row_index=row_index,
        source_row=cast(tuple[str, str, str, str, str], source_row),
        landing_key=landing_key,
        source_revision_hash=source_revision_hash,
        trade_date=trade_date,
        open_index=open_index,
        high_index=high_index,
        low_index=low_index,
        close_index=close_index,
    )


def normalize_taiex_monthly_ohlc(payload: ProviderPayload) -> NormalizedTaiexOhlcBatch:
    """Fail closed unless one complete official monthly OHLC payload is valid."""

    if (
        payload.provider != "TWSE"
        or payload.dataset != TAIEX_MONTHLY_OHLC_DATASET
        or payload.source_version != TAIEX_MONTHLY_OHLC_SOURCE_VERSION
    ):
        raise _fail(
            "TAIEX_OHLC_SOURCE_INVALID",
            "only the official TWSE English monthly TAIEX OHLC source is accepted",
        )
    raw_payload = cast(object, payload.payload)
    if not isinstance(raw_payload, Mapping):
        raise _fail("TAIEX_OHLC_PAYLOAD_INVALID", "TAIEX payload must be an object")
    body = cast(Mapping[str, object], raw_payload)
    if body.get("stat") != "OK":
        raise _fail(
            "TAIEX_OHLC_STAT_NOT_OK",
            "TAIEX provider response did not report OK",
        )
    raw_fields = body.get("fields")
    fields = cast(list[object], raw_fields) if isinstance(raw_fields, list) else None
    if fields is None or tuple(fields) != TAIEX_OHLC_FIELDS:
        raise _fail(
            "TAIEX_OHLC_FIELDS_MISMATCH",
            "TAIEX response fields do not match the OHLC contract",
        )
    requested_month = _requested_month(payload)
    response_date = _response_month(body.get("date"), requested_month)
    raw_data = body.get("data")
    raw_rows = cast(list[object], raw_data) if isinstance(raw_data, list) else None
    if not raw_rows:
        raise _fail(
            "TAIEX_OHLC_DATA_EMPTY",
            "TAIEX response must contain at least one OHLC row",
        )
    rows = tuple(
        _observation(raw, row_index=index, requested_month=requested_month)
        for index, raw in enumerate(raw_rows)
    )
    dates = [row.trade_date for row in rows]
    if len(dates) != len(set(dates)):
        raise _fail(
            "TAIEX_OHLC_DUPLICATE_TRADE_DATE",
            "TAIEX response contains duplicate trade dates",
        )
    if dates != sorted(dates):
        raise _fail(
            "TAIEX_OHLC_TRADE_DATES_NOT_ASCENDING",
            "TAIEX response trade dates must be strictly ascending",
        )
    return NormalizedTaiexOhlcBatch(
        requested_month=requested_month,
        response_date=response_date,
        source_version=payload.source_version,
        source_url=payload.source_url,
        source_payload_sha256=payload.payload_sha256,
        retrieved_at=payload.retrieved_at,
        rows=rows,
    )
