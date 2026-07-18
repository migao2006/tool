"""Shared provider implementation for provenance-safe JSON fetches."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Mapping

from .contracts import ProviderPayload
from .http import JsonHttpClient


class JsonProviderClient:
    provider_name = "UNSET"
    source_version = "UNSET"
    base_url = ""

    def __init__(self, *, http: JsonHttpClient | None = None) -> None:
        self.http = http or JsonHttpClient()

    def _get(
        self,
        *,
        dataset: str,
        base_url: str | None = None,
        path: str = "",
        params: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
        sensitive_query_keys: tuple[str, ...] = (),
        request_metadata: Mapping[str, str] | None = None,
        source_version: str | None = None,
    ) -> ProviderPayload:
        response = self.http.get_json(
            base_url=base_url or self.base_url,
            path=path,
            params=params,
            headers=headers,
            sensitive_query_keys=sensitive_query_keys,
        )
        canonical = json.dumps(
            response.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return ProviderPayload(
            provider=self.provider_name,
            dataset=dataset,
            source_version=source_version or self.source_version,
            source_url=response.safe_url,
            retrieved_at=datetime.now(timezone.utc),
            payload_sha256=sha256(canonical).hexdigest(),
            payload=response.payload,
            request_metadata=dict(request_metadata or {}),
        )
