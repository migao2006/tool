"""Server-side Supabase Data API connectivity client."""

from __future__ import annotations

from .base import JsonProviderClient
from .contracts import ProviderPayload
from .errors import (
    ProviderConfigurationError,
    ProviderCredentialError,
    ProviderHttpError,
    ProviderPayloadError,
)
from .supabase_credentials import (
    classify_server_key,
    normalize_server_key,
    rejected_key_reason,
)


class SupabaseDataClient(JsonProviderClient):
    provider_name = "SUPABASE_WRITE"
    source_version = "postgrest.v1"
    base_url = ""

    def __init__(self, *, url: str | None, service_role_key: str | None, http=None) -> None:
        super().__init__(http=http)
        self.base_url = f"{url.rstrip('/')}/rest/v1" if url else ""
        self._service_role_key = normalize_server_key(service_role_key)

    def healthcheck(self) -> ProviderPayload:
        if not self.base_url or not self._service_role_key:
            raise ProviderConfigurationError(
                "SUPABASE_WRITE_CREDENTIALS_MISSING",
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for server-side writes",
            )
        headers = {
            "apikey": self._service_role_key,
            "Accept-Profile": "market_data",
        }
        # Opaque sb_* keys are API keys, not JWTs. The hosted gateway derives
        # the service role from `apikey`; only legacy JWT keys belong in Bearer.
        if not self._service_role_key.startswith("sb_"):
            headers["Authorization"] = f"Bearer {self._service_role_key}"
        key_kind = classify_server_key(self._service_role_key)
        try:
            result = self._get(
                dataset="data_sources_health",
                path="data_sources",
                params={"select": "source_id", "limit": 1},
                headers=headers,
                request_metadata={"schema": "market_data", "access": "server_side_only"},
            )
        except ProviderHttpError as error:
            if error.status_code != 401:
                raise
            raise ProviderCredentialError(
                rejected_key_reason(key_kind),
                "Supabase rejected the configured server API key",
            ) from error
        if not isinstance(result.payload, list):
            raise ProviderPayloadError(
                "SUPABASE_DATA_API_PAYLOAD_INVALID",
                "Supabase Data API health response must be an array",
            )
        return result
