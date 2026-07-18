"""Environment-backed API settings; secret fields never appear in repr output."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
import os
from typing import Mapping


def _optional(environment: Mapping[str, str], name: str) -> str | None:
    value = environment.get(name, "").strip()
    return value or None


@dataclass(frozen=True)
class ApiProviderSettings:
    timeout_seconds: float = 20.0
    finmind_token: str | None = field(default=None, repr=False)
    fugle_api_key: str | None = field(default=None, repr=False)
    fred_api_key: str | None = field(default=None, repr=False)
    twelve_data_api_key: str | None = field(default=None, repr=False)
    supabase_url: str | None = None
    supabase_service_role_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isfinite(self.timeout_seconds) or self.timeout_seconds <= 0 or self.timeout_seconds > 120:
            raise ValueError("API timeout must be between 0 and 120 seconds")
        if self.supabase_url and not self.supabase_url.startswith("https://"):
            raise ValueError("SUPABASE_URL must use HTTPS")

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> "ApiProviderSettings":
        values = os.environ if environment is None else environment
        raw_timeout = values.get("API_HTTP_TIMEOUT_SECONDS", "20").strip()
        try:
            timeout = float(raw_timeout)
        except ValueError as error:
            raise ValueError("API_HTTP_TIMEOUT_SECONDS must be numeric") from error
        return cls(
            timeout_seconds=timeout,
            finmind_token=_optional(values, "FINMIND_TOKEN"),
            fugle_api_key=_optional(values, "FUGLE_API_KEY"),
            fred_api_key=_optional(values, "FRED_API_KEY"),
            twelve_data_api_key=_optional(values, "TWELVE_DATA_API_KEY"),
            supabase_url=_optional(values, "SUPABASE_URL"),
            supabase_service_role_key=_optional(values, "SUPABASE_SERVICE_ROLE_KEY"),
        )
