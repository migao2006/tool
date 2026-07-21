"""Private-schema Supabase REST writer with batched idempotent upserts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from http.client import HTTPResponse
import json
import re
import ssl
from typing import Protocol, cast, final
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import truststore

from src.data.providers.supabase_credentials import (
    SupabaseKeyKind,
    classify_server_key,
    normalize_server_key,
)

from .contracts import IngestionError


RPC_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class RestResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class RestTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> RestResponse: ...


@final
class UrlLibRestTransport:
    def __init__(self) -> None:
        self.ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> RestResponse:
        request = Request(url, data=body, headers=dict(headers), method=method)
        try:
            with cast(
                HTTPResponse,
                urlopen(request, timeout=timeout, context=self.ssl_context),  # noqa: S310
            ) as response:
                return RestResponse(
                    response.status, dict(response.headers.items()), response.read()
                )
        except HTTPError as error:
            return RestResponse(
                error.code,
                dict(error.headers.items()) if error.headers else {},
                error.read(),
            )
        except (OSError, TimeoutError, URLError) as error:
            raise IngestionError(
                "SUPABASE_CONNECTION_ERROR",
                "Supabase write request could not be completed",
            ) from error


@final
class SupabaseWriter:
    def __init__(
        self,
        *,
        url: str | None,
        server_key: str | None,
        schema: str = "market_data",
        timeout: float = 30.0,
        batch_size: int = 500,
        transport: RestTransport | None = None,
    ) -> None:
        normalized_key = normalize_server_key(server_key)
        if not url or not normalized_key:
            raise IngestionError(
                "SUPABASE_WRITE_CREDENTIALS_MISSING",
                "Supabase server-side write credentials are required",
            )
        key_kind = classify_server_key(normalized_key)
        if key_kind is SupabaseKeyKind.PUBLISHABLE:
            raise IngestionError(
                "SUPABASE_SERVER_KEY_REQUIRED",
                "A publishable key cannot write private market data",
            )
        if key_kind not in {SupabaseKeyKind.OPAQUE_SECRET, SupabaseKeyKind.LEGACY_JWT}:
            raise IngestionError(
                "SUPABASE_SERVER_KEY_FORMAT_INVALID",
                "The configured Supabase server key format is invalid",
            )
        if not url.startswith("https://"):
            raise IngestionError("SUPABASE_URL_INVALID", "Supabase URL must use HTTPS")
        if timeout <= 0 or batch_size <= 0:
            raise ValueError("timeout and batch_size must be positive")
        self.base_url = f"{url.rstrip('/')}/rest/v1"
        self._server_key = normalized_key
        self._legacy_jwt = key_kind is SupabaseKeyKind.LEGACY_JWT
        self.schema = schema
        self.timeout = timeout
        self.batch_size = batch_size
        self.transport = transport or UrlLibRestTransport()

    def __repr__(self) -> str:  # pyright: ignore[reportImplicitOverride]
        return f"SupabaseWriter(base_url={self.base_url!r}, schema={self.schema!r})"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Accept-Profile": self.schema,
            "Content-Profile": self.schema,
            "User-Agent": "AlphaLens-Ingestion/0.1",
            "apikey": self._server_key,
        }
        if self._legacy_jwt:
            headers["Authorization"] = f"Bearer {self._server_key}"
        return headers

    def _request(
        self,
        method: str,
        table: str,
        *,
        query: Mapping[str, str] | None = None,
        rows: Sequence[Mapping[str, object]] | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> RestResponse:
        url = f"{self.base_url}/{table}"
        if query:
            url = f"{url}?{urlencode(query)}"
        body = (
            None
            if rows is None
            else json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        response = self.transport.request(
            method,
            url,
            headers={**self._headers(), **dict(extra_headers or {})},
            body=body,
            timeout=self.timeout,
        )
        if not 200 <= response.status_code < 300:
            raise IngestionError(
                "SUPABASE_WRITE_REJECTED",
                f"Supabase rejected {method} for {table} with HTTP {response.status_code}",
            )
        return response

    def upsert(
        self,
        table: str,
        rows: Sequence[Mapping[str, object]],
        *,
        on_conflict: str,
        select: str | None = None,
        return_rows: bool = False,
        preserve_existing: bool = False,
    ) -> list[dict[str, object]]:
        if not rows:
            return []
        returned: list[dict[str, object]] = []
        for offset in range(0, len(rows), self.batch_size):
            batch = rows[offset : offset + self.batch_size]
            query = {"on_conflict": on_conflict}
            if select:
                query["select"] = select
            response = self._request(
                "POST",
                table,
                query=query,
                rows=batch,
                extra_headers={
                    "Prefer": (
                        "resolution=ignore-duplicates"
                        if preserve_existing
                        else "resolution=merge-duplicates"
                    )
                    + ",missing=default,"
                    + ("return=representation" if return_rows else "return=minimal")
                },
            )
            if return_rows:
                returned.extend(self._decode_rows(response, table=table))
        return returned

    @staticmethod
    def _decode_rows(
        response: RestResponse,
        *,
        table: str,
    ) -> list[dict[str, object]]:
        try:
            payload = cast(object, json.loads(response.body.decode("utf-8-sig")))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IngestionError(
                "SUPABASE_RESPONSE_INVALID",
                f"Supabase returned invalid JSON for {table}",
            ) from error
        if not isinstance(payload, list):
            raise IngestionError(
                "SUPABASE_RESPONSE_INVALID",
                f"Supabase returned an invalid row collection for {table}",
            )
        return [
            dict(cast(Mapping[str, object], item))
            for item in cast(list[object], payload)
            if isinstance(item, Mapping)
        ]

    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        if not select.strip():
            raise ValueError("select must not be empty")
        if limit <= 0 or offset < 0:
            raise ValueError("limit must be positive and offset must not be negative")
        response = self._request(
            "GET",
            table,
            query={
                "select": select,
                "limit": str(limit),
                "offset": str(offset),
                **dict(filters or {}),
            },
        )
        return self._decode_rows(response, table=table)

    def select_all_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        page_size: int = 1_000,
        max_rows: int = 10_000,
    ) -> list[dict[str, object]]:
        """Read a bounded, deterministic PostgREST result across pages."""

        if page_size <= 0 or max_rows <= 0 or page_size > max_rows:
            raise ValueError("page_size and max_rows are outside allowed bounds")
        rows: list[dict[str, object]] = []
        for offset in range(0, max_rows, page_size):
            page = self.select_rows(
                table,
                select=select,
                filters=filters,
                limit=min(page_size, max_rows - offset),
                offset=offset,
            )
            rows.extend(page)
            if len(page) < page_size:
                return rows
        raise IngestionError(
            "SUPABASE_SELECT_LIMIT_EXCEEDED",
            f"Supabase result for {table} exceeds the configured read limit",
        )

    def rpc(
        self,
        function_name: str,
        parameters: Mapping[str, object],
    ) -> object:
        """Call one private-schema RPC without weakening its database grants."""

        if not RPC_IDENTIFIER.fullmatch(function_name):
            raise ValueError("function_name must be a lowercase SQL identifier")
        body = json.dumps(
            dict(parameters),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        response = self.transport.request(
            "POST",
            f"{self.base_url}/rpc/{function_name}",
            headers=self._headers(),
            body=body,
            timeout=self.timeout,
        )
        if not 200 <= response.status_code < 300:
            raise IngestionError(
                "SUPABASE_RPC_REJECTED",
                (
                    "Supabase rejected POST for "
                    f"rpc/{function_name} with HTTP {response.status_code}"
                ),
            )
        try:
            return cast(object, json.loads(response.body.decode("utf-8-sig")))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IngestionError(
                "SUPABASE_RESPONSE_INVALID",
                f"Supabase returned invalid JSON for rpc/{function_name}",
            ) from error

    def count_rows(
        self,
        table: str,
        *,
        filters: Mapping[str, str] | None = None,
    ) -> int:
        response = self._request(
            "GET",
            table,
            query={"select": "*", "limit": "1", **dict(filters or {})},
            extra_headers={"Prefer": "count=exact", "Range": "0-0"},
        )
        content_range = next(
            (value for key, value in response.headers.items() if key.casefold() == "content-range"),
            None,
        )
        if not content_range or "/" not in content_range:
            raise IngestionError(
                "SUPABASE_COUNT_UNAVAILABLE",
                f"Supabase did not return an exact count for {table}",
            )
        total = content_range.rsplit("/", 1)[-1]
        if not total.isdigit():
            raise IngestionError(
                "SUPABASE_COUNT_UNAVAILABLE",
                f"Supabase returned an invalid count for {table}",
            )
        return int(total)

    def refresh_home_data_status(self) -> None:
        """Refresh the public homepage aggregate after a complete import."""

        function_name = "refresh_home_data_status"
        response = self.transport.request(
            "POST",
            f"{self.base_url}/rpc/{function_name}",
            headers=self._headers(),
            body=b"{}",
            timeout=self.timeout,
        )
        if not 200 <= response.status_code < 300:
            raise IngestionError(
                "SUPABASE_WRITE_REJECTED",
                (
                    "Supabase rejected POST for "
                    f"rpc/{function_name} with HTTP {response.status_code}"
                ),
            )
