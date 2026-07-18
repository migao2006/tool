from __future__ import annotations

import json
from collections.abc import Mapping
from typing import final
from urllib.parse import parse_qs, urlsplit

from src.data.providers.http import JsonHttpClient, TransportResponse
from src.data.providers.tpex import TpexClient
from src.data.providers.twse import TwseClient


@final
class FakeTransport:
    def __init__(self, payload: object) -> None:
        self.payload: object = payload
        self.calls: list[dict[str, object]] = []

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> TransportResponse:
        self.calls.append({"url": url, "headers": dict(headers), "timeout": timeout})
        return TransportResponse(
            200,
            {"Content-Type": "application/json"},
            json.dumps(self.payload).encode(),
        )


def http_for(transport: FakeTransport) -> JsonHttpClient:
    return JsonHttpClient(
        transport=transport,
        timeout=7,
        retry_backoff_seconds=0,
    )


def test_twse_delisting_registry_uses_official_openapi_route() -> None:
    transport = FakeTransport([])

    payload = TwseClient(http=http_for(transport)).fetch("delisting_registry")

    parts = urlsplit(str(transport.calls[0]["url"]))
    assert parts.netloc == "openapi.twse.com.tw"
    assert parts.path == "/v1/company/suspendListingCsvAndHtml"
    assert payload.request_metadata["available_at_policy"] == (
        "assign_during_ingestion"
    )


def test_tpex_delisting_registry_requests_all_rows_from_official_website() -> None:
    transport = FakeTransport({"stat": "ok", "tables": []})

    payload = TpexClient(http=http_for(transport)).fetch("delisting_registry")

    parts = urlsplit(str(transport.calls[0]["url"]))
    query = parse_qs(parts.query)
    assert parts.netloc == "www.tpex.org.tw"
    assert parts.path == "/www/zh-tw/company/deListed"
    assert query["date"] == ["ALL"]
    assert query["reason"] == ["-1"]
    assert query["response"] == ["json"]
    assert query["paging-size"] == ["1000"]
    assert query["paging-offset"] == ["0"]
    assert payload.request_metadata["distribution"] == ("OFFICIAL_TPEX_WEBSITE_JSON")
    assert payload.source_version == "website-json.v1"
