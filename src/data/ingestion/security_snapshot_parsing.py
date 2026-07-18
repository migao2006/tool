"""Pure parsers for official current security-state payloads."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import re
from typing import cast

from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError
from .roc_date import parse_exchange_date, parse_optional_exchange_date


COMMON_STOCK_SYMBOL = re.compile(r"^[0-9]{4}$")
PERIOD_DATE = re.compile(r"(?<!\d)(\d{3}/?\d{2}/?\d{2}|\d{8})(?!\d)")
YES_MARKERS = {"1", "Y", "YES", "TRUE", "是", "＊", "*", "Ｙ"}


def records(payload: ProviderPayload) -> list[Mapping[str, object]]:
    raw_payload = cast(object, payload.payload)
    if not isinstance(raw_payload, list) or not all(
        isinstance(row, Mapping) for row in raw_payload
    ):
        raise IngestionError(
            "SECURITY_SNAPSHOT_PAYLOAD_INVALID",
            "Security snapshot sources must return arrays of objects",
        )
    return [cast(Mapping[str, object], row) for row in raw_payload]


def common_stock_symbol(value: object) -> str | None:
    symbol = str(value or "").strip()
    if not COMMON_STOCK_SYMBOL.fullmatch(symbol) or symbol.startswith("91"):
        return None
    return symbol


def marked(value: object) -> bool:
    return str(value or "").strip().upper() in YES_MARKERS


def profile_state(
    payload: ProviderPayload,
    *,
    market: str,
    snapshot_date: date,
) -> tuple[dict[str, str | None], date]:
    if market == "TWSE":
        symbol_key, industry_key, date_key = "公司代號", "產業別", "出表日期"
    elif market == "TPEX":
        symbol_key, industry_key, date_key = (
            "SecuritiesCompanyCode",
            "SecuritiesIndustryCode",
            "Date",
        )
    else:
        raise ValueError("market must be TWSE or TPEX")

    industries: dict[str, str | None] = {}
    source_dates: set[date] = set()
    for row in records(payload):
        symbol = common_stock_symbol(row.get(symbol_key))
        if symbol is None:
            continue
        industries[symbol] = str(row.get(industry_key) or "").strip() or None
        source_dates.add(parse_exchange_date(row.get(date_key)))
    if not industries or len(source_dates) != 1:
        raise IngestionError(
            "SECURITY_PROFILE_SNAPSHOT_INVALID",
            "Company profiles must contain one coherent source date",
        )
    source_date = next(iter(source_dates))
    if source_date > snapshot_date or (snapshot_date - source_date).days > 14:
        raise IngestionError(
            "SECURITY_PROFILE_SNAPSHOT_STALE",
            "Company profile snapshot is future-dated or too stale",
        )
    return industries, source_date


def symbols_announced_on(
    payload: ProviderPayload,
    *,
    symbol_key: str,
    date_key: str,
    snapshot_date: date,
) -> set[str]:
    symbols: set[str] = set()
    for row in records(payload):
        symbol = common_stock_symbol(row.get(symbol_key))
        if symbol is None:
            continue
        event_date = parse_optional_exchange_date(row.get(date_key))
        if event_date is not None and event_date > snapshot_date:
            raise IngestionError(
                "SECURITY_EVENT_DATE_IN_FUTURE",
                "A security-state announcement is future-dated",
            )
        if event_date == snapshot_date:
            symbols.add(symbol)
    return symbols


def active_disposals(
    payload: ProviderPayload,
    *,
    symbol_key: str,
    period_key: str,
    snapshot_date: date,
) -> set[str]:
    active: set[str] = set()
    for row in records(payload):
        symbol = common_stock_symbol(row.get(symbol_key))
        if symbol is None:
            continue
        dates: list[str] = PERIOD_DATE.findall(str(row.get(period_key) or ""))
        if len(dates) < 2:
            raise IngestionError(
                "SECURITY_DISPOSAL_PERIOD_INVALID",
                "A common-stock disposal period cannot be parsed",
            )
        start, end = parse_exchange_date(dates[0]), parse_exchange_date(dates[1])
        if start <= snapshot_date <= end:
            active.add(symbol)
    return active


def active_whole_session_suspensions(
    payload: ProviderPayload,
    *,
    symbol_key: str,
    start_key: str,
    start_time_key: str,
    resume_key: str,
    snapshot_date: date,
) -> tuple[set[str], set[str]]:
    active: set[str] = set()
    excluded_intraday: set[str] = set()
    for row in records(payload):
        symbol = common_stock_symbol(row.get(symbol_key))
        if symbol is None:
            continue
        start = parse_optional_exchange_date(row.get(start_key))
        if start is None or start > snapshot_date:
            continue
        start_time = str(row.get(start_time_key) or "").strip().replace(":", "")
        if start_time not in {"080000", "0800"}:
            excluded_intraday.add(symbol)
            continue
        resume = parse_optional_exchange_date(row.get(resume_key))
        if resume is not None and resume <= start:
            raise IngestionError(
                "SECURITY_EVENT_RANGE_INVALID",
                "A suspension resumption date must follow its start date",
            )
        if resume is None or snapshot_date < resume:
            active.add(symbol)
    return active, excluded_intraday


def restriction_state(
    payload: ProviderPayload,
    *,
    market: str,
    snapshot_date: date,
) -> tuple[set[str], set[str], set[str]]:
    altered: set[str] = set()
    periodic: set[str] = set()
    stopped: set[str] = set()
    for row in records(payload):
        symbol_key = "Code" if market == "TWSE" else "SecuritiesCompanyCode"
        symbol = common_stock_symbol(row.get(symbol_key))
        if symbol is None:
            continue
        if market == "TWSE":
            altered.add(symbol)
            if marked(row.get("PeriodicCallAuctionTrading")):
                periodic.add(symbol)
            continue
        source_date = parse_exchange_date(row.get("Date"))
        if source_date > snapshot_date:
            raise IngestionError(
                "SECURITY_RESTRICTION_DATE_IN_FUTURE",
                "A trading restriction is future-dated",
            )
        if marked(row.get("AlteredTrading")):
            altered.add(symbol)
        if marked(row.get("PeriodicTrading")):
            periodic.add(symbol)
        if marked(row.get("SuspensionOfTrading")):
            stopped.add(symbol)
    return altered, periodic, stopped
