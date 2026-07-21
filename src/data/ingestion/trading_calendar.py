"""Normalize verified historical Taiwan trading sessions without inference."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import cast
from zoneinfo import ZoneInfo

from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError


TAIPEI = ZoneInfo("Asia/Taipei")
VERIFIED_FINMIND_MARKETS = frozenset({"TWSE"})
MINIMUM_COVERAGE_RANGE_DAYS = 90
MINIMUM_WEEKDAY_COVERAGE = 0.80
MAX_BOUNDARY_GAP_DAYS = 14


def _records(payload: ProviderPayload) -> list[Mapping[str, object]]:
    if payload.provider != "FINMIND" or payload.dataset != "trading_calendar":
        raise IngestionError(
            "TRADING_CALENDAR_SOURCE_INVALID",
            "The trading calendar must come from the configured FinMind dataset",
        )
    raw_payload = payload.payload
    if not isinstance(raw_payload, Mapping):
        raise IngestionError(
            "TRADING_CALENDAR_PAYLOAD_INVALID",
            "FinMind trading-calendar payload must be an object",
        )
    typed_payload = cast(Mapping[str, object], raw_payload)
    raw_records = typed_payload.get("data")
    if not isinstance(raw_records, list) or not all(
        isinstance(row, Mapping) for row in raw_records
    ):
        raise IngestionError(
            "TRADING_CALENDAR_PAYLOAD_INVALID",
            "FinMind trading-calendar payload must contain a data array",
        )
    return [cast(Mapping[str, object], row) for row in raw_records]


def _parse_session_date(value: object) -> date:
    try:
        session_date = date.fromisoformat(str(value or "").strip())
    except ValueError as error:
        raise IngestionError(
            "TRADING_CALENDAR_DATE_INVALID",
            "Trading-calendar rows must contain ISO dates",
        ) from error
    return session_date


def _validate_coverage(
    session_dates: Sequence[date],
    *,
    start_date: date,
    end_date: date,
) -> None:
    first_session, last_session = min(session_dates), max(session_dates)
    if (first_session - start_date).days > MAX_BOUNDARY_GAP_DAYS:
        raise IngestionError(
            "TRADING_CALENDAR_START_TRUNCATED",
            "The provider response starts too far after the requested range",
        )
    if (end_date - last_session).days > MAX_BOUNDARY_GAP_DAYS:
        raise IngestionError(
            "TRADING_CALENDAR_END_TRUNCATED",
            "The provider response ends too far before the requested range",
        )
    range_days = (end_date - start_date).days + 1
    if range_days < MINIMUM_COVERAGE_RANGE_DAYS:
        return
    weekdays = sum(
        1
        for offset in range(range_days)
        if date.fromordinal(start_date.toordinal() + offset).weekday() < 5
    )
    if weekdays and len(session_dates) / weekdays < MINIMUM_WEEKDAY_COVERAGE:
        raise IngestionError(
            "TRADING_CALENDAR_COVERAGE_INCOMPLETE",
            "The provider returned too few sessions for the requested range",
        )


def normalize_finmind_trading_calendar(
    payload: ProviderPayload,
    *,
    start_date: date,
    end_date: date,
    source_id: int,
    markets: Sequence[str] = ("TWSE",),
) -> list[dict[str, object]]:
    """Return actual sessions only; non-trading days and session hours are not guessed."""

    if start_date > end_date:
        raise ValueError("start_date must not be later than end_date")
    if source_id <= 0:
        raise ValueError("source_id must be positive")
    normalized_markets = tuple(dict.fromkeys(str(market).upper() for market in markets))
    if not normalized_markets:
        raise ValueError("at least one market is required")
    unsupported = set(normalized_markets) - VERIFIED_FINMIND_MARKETS
    if unsupported:
        raise IngestionError(
            "TRADING_CALENDAR_MARKET_NOT_VERIFIED",
            "The requested market is not verified by this calendar source contract",
        )

    provider_dates = [_parse_session_date(row.get("date")) for row in _records(payload)]
    if not provider_dates:
        raise IngestionError(
            "TRADING_CALENDAR_EMPTY",
            "The provider returned no trading sessions for the requested range",
        )
    if len(set(provider_dates)) != len(provider_dates):
        raise IngestionError(
            "TRADING_CALENDAR_DUPLICATE_DATE",
            "The provider returned duplicate trading sessions",
        )

    retrieved_date = payload.retrieved_at.astimezone(TAIPEI).date()
    if end_date > retrieved_date:
        raise IngestionError(
            "TRADING_CALENDAR_FUTURE_RANGE",
            "The requested calendar range cannot extend beyond retrieval day",
        )
    for session_date in provider_dates:
        if not start_date <= session_date <= end_date:
            raise IngestionError(
                "TRADING_CALENDAR_DATE_OUT_OF_RANGE",
                "The provider returned a session outside the requested range",
            )
    _validate_coverage(provider_dates, start_date=start_date, end_date=end_date)

    available_at = payload.retrieved_at.isoformat()
    return [
        {
            "market": market,
            "trading_date": session_date.isoformat(),
            "is_trading_day": True,
            # This dataset contains dates only. Null is safer than inventing
            # historical session hours or a decision-data cutoff.
            "opens_at": None,
            "closes_at": None,
            "decision_data_cutoff_at": None,
            "source_id": source_id,
            "available_at": available_at,
        }
        for market in normalized_markets
        for session_date in sorted(provider_dates)
    ]
