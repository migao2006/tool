"""Date parsing for exchange payloads without assuming calendar days."""

from __future__ import annotations

from datetime import date

from .contracts import IngestionError


def parse_exchange_date(value: object) -> date:
    text = str(value or "").strip().replace("/", "").replace("-", "")
    if not text.isdigit():
        raise IngestionError("SOURCE_DATE_INVALID", "exchange date is missing or invalid")
    try:
        if len(text) == 8:
            year, month, day = int(text[:4]), int(text[4:6]), int(text[6:8])
        elif len(text) == 7:
            year, month, day = int(text[:3]) + 1911, int(text[3:5]), int(text[5:7])
        else:
            raise ValueError
        return date(year, month, day)
    except ValueError as error:
        raise IngestionError("SOURCE_DATE_INVALID", "exchange date is out of range") from error


def parse_optional_exchange_date(value: object) -> date | None:
    if value is None or not str(value).strip():
        return None
    return parse_exchange_date(value)
