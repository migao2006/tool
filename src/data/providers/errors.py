"""Stable provider errors that never include API credentials."""

from __future__ import annotations


class ProviderError(RuntimeError):
    """Base error with a machine-readable reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class ProviderConfigurationError(ProviderError):
    """A required credential or provider setting is unavailable."""


class ProviderConnectionError(ProviderError):
    """The remote provider could not be reached."""


class ProviderHttpError(ProviderError):
    """The provider returned a non-success HTTP status."""

    def __init__(self, status_code: int, safe_url: str) -> None:
        super().__init__(
            "PROVIDER_HTTP_ERROR",
            f"provider request failed with HTTP {status_code}: {safe_url}",
        )
        self.status_code = status_code
        self.safe_url = safe_url


class ProviderPayloadError(ProviderError):
    """The provider returned malformed or rejected JSON."""
