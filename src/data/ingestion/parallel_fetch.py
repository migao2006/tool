"""Bounded concurrent fetching for current official OpenAPI snapshots."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from concurrent.futures import FIRST_EXCEPTION, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from threading import BoundedSemaphore
from typing import Protocol

from src.data.providers.contracts import ProviderPayload


DEFAULT_GLOBAL_FETCH_LIMIT = 4
DEFAULT_PER_PROVIDER_FETCH_LIMIT = 2


class PayloadProvider(Protocol):
    """Minimal provider contract needed by the fetch coordinator."""

    def fetch(self, dataset: str) -> ProviderPayload: ...


@dataclass(frozen=True, slots=True)
class PayloadFetchRequest:
    """One named dataset request tied to its provider concurrency bucket."""

    provider_key: str
    provider: PayloadProvider
    dataset: str


def _fetch_with_global_limit(
    request: PayloadFetchRequest,
    global_slots: BoundedSemaphore,
) -> ProviderPayload:
    with global_slots:
        return request.provider.fetch(request.dataset)


def fetch_provider_payloads(
    requests: Mapping[str, PayloadFetchRequest],
    *,
    global_limit: int = DEFAULT_GLOBAL_FETCH_LIMIT,
    per_provider_limit: int = DEFAULT_PER_PROVIDER_FETCH_LIMIT,
) -> dict[str, ProviderPayload]:
    """Fetch all payloads concurrently while preserving request order.

    Each provider has its own small executor, while a shared semaphore caps the
    number of in-flight HTTP calls across all providers. The function returns
    only after every request succeeds, so callers retain their fetch-first,
    write-after-validation transaction boundary.
    """

    if global_limit < 1 or per_provider_limit < 1:
        raise ValueError("fetch concurrency limits must be positive")
    if not requests:
        return {}

    request_items = list(requests.items())
    provider_counts: dict[str, int] = defaultdict(int)
    for _, request in request_items:
        provider_counts[request.provider_key] += 1

    global_slots = BoundedSemaphore(global_limit)
    executors = {
        provider_key: ThreadPoolExecutor(
            max_workers=min(per_provider_limit, request_count),
            thread_name_prefix=f"openapi-{provider_key.lower()}",
        )
        for provider_key, request_count in provider_counts.items()
    }
    futures: dict[str, Future[ProviderPayload]] = {}
    try:
        for name, request in request_items:
            futures[name] = executors[request.provider_key].submit(
                _fetch_with_global_limit,
                request,
                global_slots,
            )

        done, pending = wait(futures.values(), return_when=FIRST_EXCEPTION)
        failures = [future for future in done if future.exception() is not None]
        if failures:
            error = next(
                future.exception()
                for name, _ in request_items
                if (future := futures[name]) in done and future.exception() is not None
            )
            for future in pending:
                _ = future.cancel()
            if error is not None:
                raise error

        return {name: futures[name].result() for name, _ in request_items}
    finally:
        for executor in executors.values():
            executor.shutdown(wait=True, cancel_futures=True)
