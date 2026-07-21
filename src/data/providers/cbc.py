"""Central Bank of the Republic of China statistical DataAPI client."""

from __future__ import annotations

from .base import JsonProviderClient
from .contracts import ProviderPayload
from .errors import ProviderPayloadError
from .validation import require_identifier


class CbcClient(JsonProviderClient):
    provider_name = "CBC"
    source_version = "data-api.json.v1"
    base_url = "https://cpx.cbc.gov.tw/API/DataAPI"

    def fetch_series(self, file_name: str) -> ProviderPayload:
        normalized_file = require_identifier(file_name, field="file_name")
        result = self._get(
            dataset=normalized_file,
            path="Get",
            params={"FileName": normalized_file},
            request_metadata={
                "file_name": normalized_file,
                "available_at_policy": "use_meta.last_updated_and_ingestion_time",
            },
        )
        if not isinstance(result.payload, dict) or not {
            "meta",
            "data",
        }.issubset(result.payload):
            raise ProviderPayloadError(
                "CBC_PAYLOAD_INVALID",
                "CBC response does not contain meta and data",
            )
        return result
