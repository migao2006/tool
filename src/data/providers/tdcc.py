"""Taiwan Depository & Clearing Corporation official OpenAPI client."""

from __future__ import annotations

from .base import JsonProviderClient
from .contracts import ProviderPayload
from .validation import require_dataset


TDCC_DATASETS = {
    "securities": "/v1/opendata/1-1",
    "holding_distribution": "/v1/opendata/1-5",
}


class TdccClient(JsonProviderClient):
    provider_name = "TDCC"
    source_version = "openapi.v1"
    base_url = "https://openapi.tdcc.com.tw"

    def fetch(self, dataset: str) -> ProviderPayload:
        name = require_dataset(dataset, TDCC_DATASETS)
        return self._get(
            dataset=name,
            path=TDCC_DATASETS[name],
            request_metadata={"frequency": "weekly_or_source_defined"},
        )
