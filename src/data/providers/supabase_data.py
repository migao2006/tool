"""Server-side Supabase Data API connectivity client."""

from __future__ import annotations

from .base import JsonProviderClient
from .contracts import ProviderPayload
from .errors import ProviderConfigurationError, ProviderPayloadError


class SupabaseDataClient(JsonProviderClient):
    provider_name = "SUPABASE_WRITE"
    source_version = "postgrest.v1"
    base_url = ""

    def __init__(self, *, url: str | None, service_role_key: str | None, http=None) -> None:
        super().__init__(http=http)
        self.base_url = f"{url.rstrip('/')}/rest/v1" if url else ""
        self._service_role_key = service_role_key.strip() if service_role_key else None

    def healthcheck(self) -> ProviderPayload:
        if not self.base_url or not self._service_role_key:
            raise ProviderConfigurationError(
                "SUPABASE_WRITE_CREDENTIALS_MISSING",
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for server-side writes",
            )
        result = self._get(
            dataset="data_sources_health",
            path="data_sources",
            params={"select": "source_id", "limit": 1},
            headers={
                "apikey": self._service_role_key,
                "Authorization": f"Bearer {self._service_role_key}",
                "Accept-Profile": "market_data",
            },
            request_metadata={"schema": "market_data", "access": "server_side_only"},
        )
        if not isinstance(result.payload, list):
            raise ProviderPayloadError(
                "SUPABASE_DATA_API_PAYLOAD_INVALID",
                "Supabase Data API health response must be an array",
            )
        return result
