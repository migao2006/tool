"""Small live probes that validate connectivity without fabricating model data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Mapping

from .errors import ProviderConfigurationError, ProviderError, ProviderHttpError


@dataclass(frozen=True)
class ProviderProbeResult:
    provider: str
    status: str
    dataset: str | None = None
    record_count: int | None = None
    reason_code: str | None = None
    http_status: int | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _probe(client: Any, provider: str, as_of_date: date) -> Any:
    start = as_of_date - timedelta(days=14)
    if provider == "TWSE":
        return client.fetch("trading_calendar")
    if provider == "TPEX":
        return client.fetch("market_index")
    if provider == "MOPS":
        return client.fetch("listed_company_profile")
    if provider == "FINMIND":
        return client.fetch("securities")
    if provider == "TAIFEX":
        return client.fetch("put_call_ratio")
    if provider == "TDCC":
        return client.fetch("securities")
    if provider == "FUGLE":
        return client.historical_candles(
            "2330", start_date=start, end_date=as_of_date, adjusted=False
        )
    if provider == "CBC":
        return client.fetch_series("BP01D01")
    if provider == "ALPHA_VANTAGE":
        return client.fetch_macro("treasury_yield_10y_daily")
    if provider == "TWELVE_DATA":
        return client.time_series("SPY", start_date=start, end_date=as_of_date, outputsize=20)
    if provider == "SUPABASE_WRITE":
        return client.healthcheck()
    raise ValueError(f"unsupported provider probe: {provider}")


def run_live_probes(
    registry: Mapping[str, Any],
    *,
    as_of_date: date,
) -> tuple[ProviderProbeResult, ...]:
    results: list[ProviderProbeResult] = []
    for provider, client in registry.items():
        try:
            payload = _probe(client, provider, as_of_date)
            results.append(
                ProviderProbeResult(
                    provider=provider,
                    status="PASS",
                    dataset=payload.dataset,
                    record_count=payload.record_count,
                )
            )
        except ProviderConfigurationError as error:
            results.append(
                ProviderProbeResult(
                    provider=provider,
                    status="NOT_CONFIGURED",
                    reason_code=error.reason_code,
                )
            )
        except ProviderHttpError as error:
            results.append(
                ProviderProbeResult(
                    provider=provider,
                    status="FAIL",
                    reason_code=error.reason_code,
                    http_status=error.status_code,
                )
            )
        except ProviderError as error:
            results.append(
                ProviderProbeResult(
                    provider=provider,
                    status="FAIL",
                    reason_code=error.reason_code,
                )
            )
        except Exception:
            results.append(
                ProviderProbeResult(
                    provider=provider,
                    status="FAIL",
                    reason_code="UNEXPECTED_PROVIDER_ERROR",
                )
            )
    return tuple(results)
