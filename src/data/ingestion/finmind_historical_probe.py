"""Bounded, read-only FinMind historical daily-bar capability probe."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
import json
from math import isfinite
from time import sleep
from typing import Protocol, cast, final

from src.data.providers.contracts import ProviderPayload
from src.data.providers.errors import ProviderError
from src.data.providers.validation import require_identifier

from .finmind_historical_probe_contracts import (
    FinMindHistoricalProbeSummary,
    FinMindQuotaSummary,
    FinMindSymbolProbe,
)


MAX_SYMBOLS = 20


class FinMindProbeClient(Protocol):
    def fetch_quota(self) -> ProviderPayload: ...

    def fetch(
        self,
        dataset: str,
        *,
        data_id: str | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> ProviderPayload: ...


class FinMindProbeError(ProviderError):
    """A bounded probe contract or safety check failed."""


def _maximum_end_date(start_date: date) -> date:
    try:
        return start_date.replace(year=start_date.year + 5)
    except ValueError:
        return start_date.replace(year=start_date.year + 5, day=28)


def validate_probe_request(
    *,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    pacing_seconds: float,
) -> tuple[str, ...]:
    if not symbols:
        raise FinMindProbeError(
            "FINMIND_PROBE_SYMBOLS_REQUIRED",
            "at least one explicit symbol is required",
        )
    if len(symbols) > MAX_SYMBOLS:
        raise FinMindProbeError(
            "FINMIND_PROBE_SYMBOL_LIMIT",
            f"at most {MAX_SYMBOLS} symbols may be probed at once",
        )
    normalized = tuple(
        require_identifier(symbol, field="symbol") for symbol in symbols
    )
    if len(set(normalized)) != len(normalized):
        raise FinMindProbeError(
            "FINMIND_PROBE_DUPLICATE_SYMBOL",
            "probe symbols must be unique",
        )
    if end_date < start_date:
        raise FinMindProbeError(
            "FINMIND_PROBE_DATE_RANGE_INVALID",
            "start_date must not be after end_date",
        )
    if end_date > _maximum_end_date(start_date):
        raise FinMindProbeError(
            "FINMIND_PROBE_DATE_RANGE_LIMIT",
            "historical probe range cannot exceed five years",
        )
    if not isfinite(pacing_seconds) or not 0 <= pacing_seconds <= 60:
        raise FinMindProbeError(
            "FINMIND_PROBE_PACING_INVALID",
            "pacing_seconds must be between 0 and 60",
        )
    return normalized


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _quota_summary(payload: ProviderPayload) -> FinMindQuotaSummary:
    body = cast(dict[str, object], payload.payload)
    used = cast(int, body["user_count"])
    limit = cast(int, body["api_request_limit"])
    return FinMindQuotaSummary(
        requests_used=used,
        request_limit=limit,
        requests_remaining=max(limit - used, 0),
        response_sha256=payload.payload_sha256,
    )


def _symbol_summary(
    payload: ProviderPayload,
    *,
    requested_symbol: str,
    start_date: date,
    end_date: date,
) -> FinMindSymbolProbe:
    body = cast(dict[str, object], payload.payload)
    rows = cast(list[object], body["data"])
    observed_symbols: set[str] = set()
    observed_dates: list[date] = []
    keys: set[tuple[str, date]] = set()
    duplicate_keys = False
    for row in rows:
        if not isinstance(row, dict):
            raise FinMindProbeError(
                "FINMIND_PROBE_ROW_INVALID",
                "FinMind daily-bar row must be a JSON object",
            )
        typed_row = cast(dict[str, object], row)
        symbol = typed_row.get("stock_id")
        raw_date = typed_row.get("date")
        if not isinstance(symbol, str) or not isinstance(raw_date, str):
            raise FinMindProbeError(
                "FINMIND_PROBE_ROW_INVALID",
                "FinMind daily-bar row requires stock_id and date",
            )
        try:
            observed_date = date.fromisoformat(raw_date)
        except ValueError as error:
            raise FinMindProbeError(
                "FINMIND_PROBE_ROW_INVALID",
                "FinMind daily-bar date must use YYYY-MM-DD",
            ) from error
        observed_symbols.add(symbol)
        observed_dates.append(observed_date)
        key = (symbol, observed_date)
        duplicate_keys = duplicate_keys or key in keys
        keys.add(key)

    reasons: list[str] = []
    if not rows:
        reasons.append("EMPTY_RESPONSE")
    if observed_symbols and observed_symbols != {requested_symbol}:
        reasons.append("SYMBOL_COVERAGE_MISMATCH")
    if any(value < start_date or value > end_date for value in observed_dates):
        reasons.append("DATE_OUTSIDE_REQUEST")
    if duplicate_keys:
        reasons.append("DUPLICATE_STOCK_DATE")

    canonical = _canonical_bytes(cast(object, payload.payload))
    return FinMindSymbolProbe(
        symbol=requested_symbol,
        rows=len(rows),
        minimum_date=min(observed_dates).isoformat() if observed_dates else None,
        maximum_date=max(observed_dates).isoformat() if observed_dates else None,
        unique_symbols=len(observed_symbols),
        response_bytes=len(canonical),
        response_encoding="canonical-json-utf8",
        response_sha256=payload.payload_sha256,
        suspected_truncation=bool(reasons),
        truncation_reasons=tuple(reasons),
    )


@final
class FinMindHistoricalProbe:
    def __init__(
        self,
        *,
        client: FinMindProbeClient,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        self._client: FinMindProbeClient = client
        self._sleep: Callable[[float], None] = sleep_fn

    def run(
        self,
        *,
        symbols: Sequence[str],
        start_date: date,
        end_date: date,
        pacing_seconds: float,
    ) -> FinMindHistoricalProbeSummary:
        normalized = validate_probe_request(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            pacing_seconds=pacing_seconds,
        )
        quota = _quota_summary(self._client.fetch_quota())
        if quota.requests_remaining < len(normalized):
            raise FinMindProbeError(
                "FINMIND_PROBE_QUOTA_INSUFFICIENT",
                "FinMind quota is insufficient for the bounded probe",
            )

        results: list[FinMindSymbolProbe] = []
        for symbol in normalized:
            if pacing_seconds:
                self._sleep(pacing_seconds)
            payload = self._client.fetch(
                "daily_bars",
                data_id=symbol,
                start_date=start_date,
                end_date=end_date,
            )
            results.append(
                _symbol_summary(
                    payload,
                    requested_symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                )
            )

        return FinMindHistoricalProbeSummary(
            status="RESEARCH_ONLY",
            provider="FINMIND",
            remote_dataset="TaiwanStockPrice",
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            requested_symbols=normalized,
            pacing_seconds=pacing_seconds,
            quota=quota,
            symbols=tuple(results),
            total_rows=sum(result.rows for result in results),
        )
