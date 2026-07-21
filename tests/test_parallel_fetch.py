from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from threading import Lock
from time import sleep
from typing import final

import pytest

from src.data.ingestion.parallel_fetch import (
    PayloadFetchRequest,
    fetch_provider_payloads,
)
from src.data.providers.contracts import ProviderPayload


def _payload(provider: str, dataset: str) -> ProviderPayload:
    rows = [{"provider": provider, "dataset": dataset}]
    digest = sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    return ProviderPayload(
        provider=provider,
        dataset=dataset,
        source_version="openapi.v1",
        source_url="https://example.test/openapi",
        retrieved_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        payload_sha256=digest,
        payload=rows,
    )


@final
class ConcurrencyTracker:
    def __init__(self) -> None:
        self._lock = Lock()
        self.active = 0
        self.max_active = 0
        self.active_by_provider: dict[str, int] = defaultdict(int)
        self.max_by_provider: dict[str, int] = defaultdict(int)

    def start(self, provider: str) -> None:
        with self._lock:
            self.active += 1
            self.active_by_provider[provider] += 1
            self.max_active = max(self.max_active, self.active)
            self.max_by_provider[provider] = max(
                self.max_by_provider[provider],
                self.active_by_provider[provider],
            )

    def finish(self, provider: str) -> None:
        with self._lock:
            self.active -= 1
            self.active_by_provider[provider] -= 1


@final
class TrackingProvider:
    def __init__(self, name: str, tracker: ConcurrencyTracker) -> None:
        self.name = name
        self.tracker = tracker

    def fetch(self, dataset: str) -> ProviderPayload:
        self.tracker.start(self.name)
        try:
            sleep(0.05)
            return _payload(self.name, dataset)
        finally:
            self.tracker.finish(self.name)


def test_fetches_use_global_and_per_provider_bounds_with_stable_result_order() -> None:
    tracker = ConcurrencyTracker()
    providers = {name: TrackingProvider(name, tracker) for name in ("TWSE", "TPEX")}
    requests = {
        **{
            f"twse_{index}": PayloadFetchRequest(
                "TWSE", providers["TWSE"], f"dataset_{index}"
            )
            for index in range(4)
        },
        **{
            f"tpex_{index}": PayloadFetchRequest(
                "TPEX", providers["TPEX"], f"dataset_{index}"
            )
            for index in range(4)
        },
    }

    payloads = fetch_provider_payloads(requests)

    assert list(payloads) == list(requests)
    assert tracker.max_active == 4
    assert tracker.max_by_provider == {"TWSE": 2, "TPEX": 2}
    assert payloads["twse_0"].dataset == "dataset_0"
    assert payloads["tpex_3"].provider == "TPEX"


@final
class FailingProvider:
    def fetch(self, dataset: str) -> ProviderPayload:
        raise RuntimeError(f"failed:{dataset}")


def test_fetch_failure_is_propagated_instead_of_returning_partial_payloads() -> None:
    tracker = ConcurrencyTracker()
    requests = {
        "failed": PayloadFetchRequest("TWSE", FailingProvider(), "broken"),
        "other": PayloadFetchRequest(
            "TPEX", TrackingProvider("TPEX", tracker), "return_index"
        ),
    }

    with pytest.raises(RuntimeError, match="failed:broken"):
        _ = fetch_provider_payloads(requests)


@pytest.mark.parametrize(
    ("global_limit", "per_provider_limit"),
    [(0, 1), (1, 0), (-1, 2)],
)
def test_fetch_rejects_non_positive_concurrency_limits(
    global_limit: int,
    per_provider_limit: int,
) -> None:
    with pytest.raises(ValueError, match="positive"):
        _ = fetch_provider_payloads(
            {},
            global_limit=global_limit,
            per_provider_limit=per_provider_limit,
        )
