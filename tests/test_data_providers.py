from __future__ import annotations

from datetime import date
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts.check_data_apis import build_report
from src.data.providers.cbc import CbcClient
from src.data.providers.errors import (
    ProviderConfigurationError,
    ProviderHttpError,
    ProviderPayloadError,
)
from src.data.providers.finmind import FinMindClient
from src.data.providers.fetcher import ProviderFetchRequest, fetch_provider_payload
from src.data.providers.fred import FredClient
from src.data.providers.fugle import FugleClient
from src.data.providers.http import JsonHttpClient, TransportResponse
from src.data.providers.mops import MopsClient
from src.data.providers.registry import build_provider_registry, provider_readiness
from src.data.providers.settings import ApiProviderSettings
from src.data.providers.supabase_data import SupabaseDataClient
from src.data.providers.taifex import TaifexClient
from src.data.providers.tdcc import TdccClient
from src.data.providers.tpex import TpexClient
from src.data.providers.twelve_data import TwelveDataClient
from src.data.providers.twse import TwseClient


class FakeTransport:
    def __init__(self, payload: object, *, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, headers, timeout: float) -> TransportResponse:
        self.calls.append({"url": url, "headers": dict(headers), "timeout": timeout})
        body = self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()
        return TransportResponse(self.status_code, {"Content-Type": "application/json"}, body)


def http_for(transport: FakeTransport) -> JsonHttpClient:
    return JsonHttpClient(transport=transport, timeout=7)


def test_registry_contains_all_market_data_providers_and_supabase_sink() -> None:
    settings = ApiProviderSettings()
    registry = build_provider_registry(settings, transport=FakeTransport([]))
    assert set(registry) == {
        "TWSE",
        "TPEX",
        "MOPS",
        "FINMIND",
        "TAIFEX",
        "TDCC",
        "FUGLE",
        "CBC",
        "FRED",
        "TWELVE_DATA",
        "SUPABASE_WRITE",
    }


def test_readiness_lists_public_private_and_supabase_write_settings() -> None:
    settings = ApiProviderSettings.from_env(
        {
            "FINMIND_TOKEN": "finmind",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-secret",
        }
    )
    readiness = {item.provider: item for item in provider_readiness(settings)}
    assert readiness["TWSE"].configured
    assert readiness["FINMIND"].configured
    assert readiness["SUPABASE_WRITE"].configured
    assert not readiness["FRED"].configured
    assert readiness["FRED"].reason_code == "CREDENTIAL_NOT_CONFIGURED"


def test_settings_repr_never_contains_secrets() -> None:
    settings = ApiProviderSettings(
        finmind_token="finmind-secret",
        fugle_api_key="fugle-secret",
        fred_api_key="fred-secret",
        twelve_data_api_key="twelve-secret",
        supabase_service_role_key="supabase-secret",
    )
    rendered = repr(settings)
    for secret in ("finmind-secret", "fugle-secret", "fred-secret", "twelve-secret", "supabase-secret"):
        assert secret not in rendered


def test_settings_reject_non_finite_timeout() -> None:
    with pytest.raises(ValueError, match="timeout"):
        ApiProviderSettings(timeout_seconds=float("nan"))


def test_supabase_healthcheck_uses_private_headers_without_leaking_key() -> None:
    transport = FakeTransport([])
    payload = SupabaseDataClient(
        url="https://example.supabase.co",
        service_role_key="service-secret",
        http=http_for(transport),
    ).healthcheck()
    call = transport.calls[0]
    assert call["headers"]["Accept-Profile"] == "market_data"
    assert call["headers"]["Authorization"] == "Bearer service-secret"
    assert "service-secret" not in payload.source_url


@pytest.mark.parametrize(
    ("client", "dataset", "expected_path"),
    [
        (TwseClient, "daily_bars", "/exchangeReport/STOCK_DAY_ALL"),
        (TpexClient, "institutional_flows", "/tpex_3insti_daily_trading"),
        (TaifexClient, "put_call_ratio", "/PutCallRatio"),
        (TdccClient, "holding_distribution", "/v1/opendata/1-5"),
    ],
)
def test_public_provider_dataset_routes(client, dataset: str, expected_path: str) -> None:
    transport = FakeTransport([{"value": "1"}])
    payload = client(http=http_for(transport)).fetch(dataset)
    assert urlsplit(str(transport.calls[0]["url"])).path.endswith(expected_path)
    assert payload.record_count == 1
    assert payload.retrieved_at.tzinfo is not None
    assert len(payload.payload_sha256) == 64


def test_mops_uses_official_tpex_distribution_for_otc_data() -> None:
    transport = FakeTransport([])
    payload = MopsClient(http=http_for(transport)).fetch("otc_monthly_revenue")
    assert urlsplit(str(transport.calls[0]["url"])).netloc == "www.tpex.org.tw"
    assert payload.request_metadata["distribution"] == "MOPS_VIA_EXCHANGE_OPENAPI"


def test_fetcher_dispatches_provider_without_combining_source_logic() -> None:
    transport = FakeTransport([])
    registry = {"TWSE": TwseClient(http=http_for(transport))}
    payload = fetch_provider_payload(
        registry,
        ProviderFetchRequest(provider="twse", dataset="daily_bars"),
    )
    assert payload.provider == "TWSE"
    assert payload.dataset == "daily_bars"


def test_finmind_uses_bearer_header_without_leaking_token() -> None:
    transport = FakeTransport({"status": 200, "data": []})
    payload = FinMindClient(token="finmind-secret", http=http_for(transport)).fetch(
        "daily_bars",
        data_id="2330",
        start_date="2026-07-01",
        end_date="2026-07-18",
    )
    call = transport.calls[0]
    assert call["headers"]["Authorization"] == "Bearer finmind-secret"
    assert "finmind-secret" not in payload.source_url
    assert parse_qs(urlsplit(str(call["url"])).query)["dataset"] == ["TaiwanStockPrice"]


@pytest.mark.parametrize(
    ("factory", "reason_code"),
    [
        (lambda: FinMindClient(token=None), "FINMIND_TOKEN_MISSING"),
        (lambda: FugleClient(api_key=None), "FUGLE_API_KEY_MISSING"),
        (lambda: FredClient(api_key=None), "FRED_API_KEY_MISSING"),
        (lambda: TwelveDataClient(api_key=None), "TWELVE_DATA_API_KEY_MISSING"),
    ],
)
def test_private_providers_fail_closed_without_credentials(factory, reason_code: str) -> None:
    client = factory()
    with pytest.raises(ProviderConfigurationError) as captured:
        if isinstance(client, FinMindClient):
            client.fetch("securities")
        elif isinstance(client, FugleClient):
            client.historical_candles("2330", start_date="2026-07-01", end_date="2026-07-18")
        elif isinstance(client, FredClient):
            client.observations("DGS10", as_of_date="2026-07-18")
        else:
            client.time_series("SPY", start_date="2026-07-01", end_date="2026-07-18")
    assert captured.value.reason_code == reason_code


def test_fred_requires_vintage_and_redacts_api_key() -> None:
    transport = FakeTransport({"observations": []})
    payload = FredClient(api_key="fred-secret", http=http_for(transport)).observations(
        "DGS10",
        as_of_date="2026-07-17",
        observation_start="2026-07-01",
    )
    query = parse_qs(urlsplit(str(transport.calls[0]["url"])).query)
    assert query["realtime_start"] == ["2026-07-17"]
    assert query["realtime_end"] == ["2026-07-17"]
    assert "fred-secret" not in payload.source_url
    assert "%5BREDACTED%5D" in payload.source_url or "REDACTED" in payload.source_url


def test_twelve_data_uses_daily_utc_series_and_redacts_key() -> None:
    transport = FakeTransport({"status": "ok", "values": []})
    payload = TwelveDataClient(
        api_key="twelve-secret", http=http_for(transport)
    ).time_series("SPY", start_date="2026-07-01", end_date="2026-07-18")
    query = parse_qs(urlsplit(str(transport.calls[0]["url"])).query)
    assert query["interval"] == ["1day"]
    assert query["timezone"] == ["UTC"]
    assert "twelve-secret" not in payload.source_url


def test_fugle_rejects_path_injection() -> None:
    client = FugleClient(api_key="key", http=http_for(FakeTransport({"data": []})))
    with pytest.raises(ValueError, match="path"):
        client.historical_candles("../2330", start_date="2026-07-01", end_date="2026-07-18")


def test_providers_reject_reversed_date_ranges() -> None:
    client = FugleClient(api_key="key", http=http_for(FakeTransport({"data": []})))
    with pytest.raises(ValueError, match="start_date"):
        client.historical_candles("2330", start_date="2026-07-18", end_date="2026-07-01")


def test_cbc_preserves_matrix_payload_and_counts_rows() -> None:
    transport = FakeTransport(
        {"meta": {"last_updated": "2026-07-17"}, "data": {"dataSets": [["20260717", "32.1"]]}}
    )
    payload = CbcClient(http=http_for(transport)).fetch_series("BP01D01")
    assert payload.record_count == 1
    assert payload.request_metadata["file_name"] == "BP01D01"


def test_http_errors_and_invalid_json_have_stable_reason_codes() -> None:
    denied = TwseClient(http=http_for(FakeTransport({"error": "denied"}, status_code=429)))
    with pytest.raises(ProviderHttpError) as http_error:
        denied.fetch("daily_bars")
    assert http_error.value.status_code == 429

    invalid = TwseClient(http=http_for(FakeTransport(b"not-json")))
    with pytest.raises(ProviderPayloadError) as payload_error:
        invalid.fetch("daily_bars")
    assert payload_error.value.reason_code == "PROVIDER_INVALID_JSON"


def test_configuration_report_is_research_only_until_keys_exist(monkeypatch) -> None:
    for name in (
        "FINMIND_TOKEN",
        "FUGLE_API_KEY",
        "FRED_API_KEY",
        "TWELVE_DATA_API_KEY",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    report, exit_code = build_report(live=False, as_of_date=date(2026, 7, 18))
    assert report["status"] == "RESEARCH_ONLY"
    assert exit_code == 0
