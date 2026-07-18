"""Explicit dispatch from a CLI request to one provider method."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from .contracts import ProviderPayload


@dataclass(frozen=True)
class ProviderFetchRequest:
    provider: str
    dataset: str | None = None
    symbol: str | None = None
    series_id: str | None = None
    file_name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    as_of_date: date | None = None
    adjusted: bool = False


def _required(value: Any, name: str) -> Any:
    if value is None or value == "":
        raise ValueError(f"{name} is required for this provider")
    return value


def fetch_provider_payload(
    registry: Mapping[str, Any], request: ProviderFetchRequest
) -> ProviderPayload:
    provider = request.provider.upper()
    if provider not in registry:
        raise ValueError(f"unsupported provider: {request.provider}")
    client = registry[provider]
    if provider in {"TWSE", "TPEX", "MOPS", "TAIFEX", "TDCC"}:
        return client.fetch(_required(request.dataset, "dataset"))
    if provider == "FINMIND":
        return client.fetch(
            _required(request.dataset, "dataset"),
            data_id=request.symbol,
            start_date=request.start_date,
            end_date=request.end_date,
        )
    if provider == "FUGLE":
        return client.historical_candles(
            _required(request.symbol, "symbol"),
            start_date=_required(request.start_date, "start_date"),
            end_date=_required(request.end_date, "end_date"),
            adjusted=request.adjusted,
        )
    if provider == "CBC":
        return client.fetch_series(_required(request.file_name, "file_name"))
    if provider == "FRED":
        return client.observations(
            _required(request.series_id, "series_id"),
            as_of_date=_required(request.as_of_date, "as_of_date"),
            observation_start=request.start_date,
            observation_end=request.end_date,
        )
    if provider == "TWELVE_DATA":
        return client.time_series(
            _required(request.symbol, "symbol"),
            start_date=_required(request.start_date, "start_date"),
            end_date=_required(request.end_date, "end_date"),
        )
    if provider == "SUPABASE_WRITE":
        return client.healthcheck()
    raise ValueError(f"provider has no fetch route: {provider}")
