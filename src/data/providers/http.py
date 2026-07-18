"""Small dependency-free JSON HTTP client with credential redaction."""

from __future__ import annotations

from dataclasses import dataclass
from http.client import HTTPException
import json
import ssl
from time import sleep
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import truststore

from .errors import (
    ProviderConnectionError,
    ProviderHttpError,
    ProviderPayloadError,
)


REDACTED = "[REDACTED]"
TRANSIENT_HTTP_STATUSES = {408, 425, 429}


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class HttpTransport(Protocol):
    def get(self, url: str, *, headers: Mapping[str, str], timeout: float) -> TransportResponse: ...


class UrlLibTransport:
    """Production GET transport; tests inject an in-memory implementation."""

    def __init__(self) -> None:
        self.ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    def get(self, url: str, *, headers: Mapping[str, str], timeout: float) -> TransportResponse:
        request = Request(url, headers=dict(headers), method="GET")
        try:
            with urlopen(  # noqa: S310 - fixed HTTPS providers
                request,
                timeout=timeout,
                context=self.ssl_context,
            ) as response:
                return TransportResponse(
                    status_code=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except HTTPError as error:
            return TransportResponse(
                status_code=error.code,
                headers=dict(error.headers.items()) if error.headers else {},
                body=error.read(),
            )
        except (HTTPException, OSError) as error:
            raise ProviderConnectionError(
                "PROVIDER_CONNECTION_ERROR",
                "provider request could not be completed",
            ) from error


@dataclass(frozen=True)
class JsonHttpResponse:
    safe_url: str
    status_code: int
    headers: Mapping[str, str]
    payload: Any


def redact_url(url: str, sensitive_query_keys: tuple[str, ...] = ()) -> str:
    sensitive = {key.casefold() for key in sensitive_query_keys}
    parts = urlsplit(url)
    safe_query = urlencode(
        [
            (key, REDACTED if key.casefold() in sensitive else value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, safe_query, parts.fragment))


class JsonHttpClient:
    def __init__(
        self,
        *,
        transport: HttpTransport | None = None,
        timeout: float = 20.0,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds cannot be negative")
        self.transport = transport or UrlLibTransport()
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds

    def _get_with_retries(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
    ) -> TransportResponse:
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.transport.get(url, headers=headers, timeout=self.timeout)
            except ProviderConnectionError:
                if attempt == self.max_attempts:
                    raise
            else:
                is_transient = (
                    response.status_code in TRANSIENT_HTTP_STATUSES
                    or 500 <= response.status_code < 600
                )
                if not is_transient or attempt == self.max_attempts:
                    return response
            delay = self.retry_backoff_seconds * (2 ** (attempt - 1))
            if delay:
                sleep(delay)
        raise AssertionError("retry loop exhausted without returning or raising")

    def get_json(
        self,
        *,
        base_url: str,
        path: str = "",
        params: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
        sensitive_query_keys: tuple[str, ...] = (),
    ) -> JsonHttpResponse:
        if not base_url.startswith("https://"):
            raise ValueError("provider base_url must use HTTPS")
        url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        filtered_params = {
            key: value for key, value in (params or {}).items() if value is not None
        }
        if filtered_params:
            url = f"{url}?{urlencode(filtered_params, doseq=True)}"
        safe_url = redact_url(url, sensitive_query_keys)
        response = self._get_with_retries(
            url,
            headers={"Accept": "application/json", "User-Agent": "AlphaLens/0.1", **(headers or {})},
        )
        if not 200 <= response.status_code < 300:
            raise ProviderHttpError(response.status_code, safe_url)
        try:
            text = response.body.decode("utf-8-sig")
            payload = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderPayloadError(
                "PROVIDER_INVALID_JSON",
                f"provider returned invalid JSON: {safe_url}",
            ) from error
        return JsonHttpResponse(
            safe_url=safe_url,
            status_code=response.status_code,
            headers=dict(response.headers),
            payload=payload,
        )
