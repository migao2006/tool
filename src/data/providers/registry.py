"""Provider construction and credential readiness reporting."""

from __future__ import annotations

from typing import Any

from .cbc import CbcClient
from .contracts import ProviderReadiness
from .finmind import FinMindClient
from .fred import FredClient
from .fugle import FugleClient
from .http import HttpTransport, JsonHttpClient
from .mops import MopsClient
from .settings import ApiProviderSettings
from .supabase_data import SupabaseDataClient
from .taifex import TaifexClient
from .tdcc import TdccClient
from .tpex import TpexClient
from .twelve_data import TwelveDataClient
from .twse import TwseClient


PUBLIC_PROVIDERS = ("TWSE", "TPEX", "MOPS", "TAIFEX", "TDCC", "CBC")


def build_provider_registry(
    settings: ApiProviderSettings,
    *,
    transport: HttpTransport | None = None,
) -> dict[str, Any]:
    http = JsonHttpClient(transport=transport, timeout=settings.timeout_seconds)
    return {
        "TWSE": TwseClient(http=http),
        "TPEX": TpexClient(http=http),
        "MOPS": MopsClient(http=http),
        "FINMIND": FinMindClient(token=settings.finmind_token, http=http),
        "TAIFEX": TaifexClient(http=http),
        "TDCC": TdccClient(http=http),
        "FUGLE": FugleClient(api_key=settings.fugle_api_key, http=http),
        "CBC": CbcClient(http=http),
        "FRED": FredClient(api_key=settings.fred_api_key, http=http),
        "TWELVE_DATA": TwelveDataClient(api_key=settings.twelve_data_api_key, http=http),
        "SUPABASE_WRITE": SupabaseDataClient(
            url=settings.supabase_url,
            service_role_key=settings.supabase_service_role_key,
            http=http,
        ),
    }


def provider_readiness(settings: ApiProviderSettings) -> tuple[ProviderReadiness, ...]:
    statuses = [
        ProviderReadiness(name, True, ()) for name in PUBLIC_PROVIDERS
    ]
    protected = (
        ("FINMIND", settings.finmind_token, ("FINMIND_TOKEN",)),
        ("FUGLE", settings.fugle_api_key, ("FUGLE_API_KEY",)),
        ("FRED", settings.fred_api_key, ("FRED_API_KEY",)),
        ("TWELVE_DATA", settings.twelve_data_api_key, ("TWELVE_DATA_API_KEY",)),
        (
            "SUPABASE_WRITE",
            settings.supabase_url and settings.supabase_service_role_key,
            ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"),
        ),
    )
    statuses.extend(
        ProviderReadiness(
            provider=name,
            configured=bool(value),
            credential_environment_variables=variables,
            reason_code=None if value else "CREDENTIAL_NOT_CONFIGURED",
        )
        for name, value, variables in protected
    )
    return tuple(sorted(statuses, key=lambda status: status.provider))
