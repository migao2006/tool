"""Server-side Supabase Data API connectivity client."""

from __future__ import annotations

from .base import JsonProviderClient
from .contracts import ProviderPayload
from .errors import ProviderConfigurationError, ProviderPayloadError


def _normalize_server_key(value: str | None) -> str | None:
    """Normalize common GitHub Secret paste forms without exposing the key."""

    if not value:
        return None
    normalized = value.strip()
    for _ in range(2):
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in "\"'":
            normalized = normalized[1:-1].strip()
        for variable in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY"):
            if normalized.upper().startswith(f"{variable}="):
                normalized = normalized.split("=", 1)[1].strip()
                break
    return normalized or None


class SupabaseDataClient(JsonProviderClient):
    provider_name = "SUPABASE_WRITE"
    source_version = "postgrest.v1"
    base_url = ""

    def __init__(self, *, url: str | None, service_role_key: str | None, http=None) -> None:
        super().__init__(http=http)
        self.base_url = f"{url.rstrip('/')}/rest/v1" if url else ""
        self._service_role_key = _normalize_server_key(service_role_key)

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
        result = self._get(
            dataset="data_sources_health",
            path="data_sources",
            params={"select": "source_id", "limit": 1},
            headers=headers,
            request_metadata={"schema": "market_data", "access": "server_side_only"},
        )
        if not isinstance(result.payload, list):
            raise ProviderPayloadError(
                "SUPABASE_DATA_API_PAYLOAD_INVALID",
                "Supabase Data API health response must be an array",
            )
        return result
