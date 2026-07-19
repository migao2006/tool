"""Quota planning, fetch pacing, and normalization for evidence batches."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Protocol, cast

from src.data.providers.contracts import ProviderPayload

from .contracts import IngestionError
from .finmind_historical_evidence import normalize_finmind_historical_evidence
from .finmind_historical_evidence_contracts import (
    HistoricalEvidenceIdentity,
    NormalizedFinMindHistoricalEvidence,
)


GLOBAL_DATASETS = ("stock_splits", "par_value_changes", "suspended")
IMPORT_SCOPES = frozenset({"ALL", "DIVIDENDS", "GLOBAL"})


class FinMindHistoricalEvidenceProvider(Protocol):
    def fetch_quota(self) -> ProviderPayload: ...

    def fetch(
        self,
        dataset: str,
        *,
        data_id: str | None = None,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> ProviderPayload: ...


def datasets_for_scope(scope: str) -> frozenset[str]:
    normalized = scope.strip().upper()
    if normalized not in IMPORT_SCOPES:
        raise IngestionError(
            "FINMIND_HISTORICAL_SCOPE_INVALID",
            "scope must be ALL, DIVIDENDS, or GLOBAL",
        )
    datasets: set[str] = set(GLOBAL_DATASETS if normalized in {"ALL", "GLOBAL"} else ())
    if normalized in {"ALL", "DIVIDENDS"}:
        datasets.add("dividend_results")
    return frozenset(datasets)


def quota_remaining(payload: ProviderPayload) -> int:
    raw = cast(object, payload.payload)
    if not isinstance(raw, Mapping):
        raise IngestionError(
            "FINMIND_QUOTA_PAYLOAD_INVALID", "FinMind quota must be an object"
        )
    counters = cast(Mapping[str, object], raw)
    used = counters.get("user_count")
    limit = counters.get("api_request_limit")
    if (
        isinstance(used, bool)
        or not isinstance(used, int)
        or isinstance(limit, bool)
        or not isinstance(limit, int)
        or min(used, limit) < 0
    ):
        raise IngestionError(
            "FINMIND_QUOTA_PAYLOAD_INVALID",
            "FinMind quota response is missing documented counters",
        )
    return max(limit - used, 0)


def fetch_evidence_payloads(
    provider: FinMindHistoricalEvidenceProvider,
    *,
    symbols: Sequence[str],
    start_date: date,
    end_date: date,
    pacing_seconds: float,
    scope: str,
    sleep_fn: Callable[[float], None],
) -> tuple[ProviderPayload, ...]:
    datasets = datasets_for_scope(scope)
    requests: list[tuple[str, str | None]] = (
        [("dividend_results", symbol) for symbol in symbols]
        if "dividend_results" in datasets
        else []
    )
    requests.extend(
        (dataset, None) for dataset in GLOBAL_DATASETS if dataset in datasets
    )
    payloads: list[ProviderPayload] = []
    for index, (dataset, data_id) in enumerate(requests):
        if index and pacing_seconds:
            sleep_fn(pacing_seconds)
        payloads.append(
            provider.fetch(
                dataset,
                data_id=data_id,
                start_date=start_date,
                end_date=end_date,
            )
        )
    return tuple(payloads)


def _merge_normalized(
    parts: Sequence[NormalizedFinMindHistoricalEvidence],
) -> NormalizedFinMindHistoricalEvidence:
    return NormalizedFinMindHistoricalEvidence(
        action_rows=tuple(row for part in parts for row in part.action_rows),
        state_event_rows=tuple(row for part in parts for row in part.state_event_rows),
        input_rows=sum(part.input_rows for part in parts),
        excluded_outside_request=sum(part.excluded_outside_request for part in parts),
        excluded_outside_range=sum(part.excluded_outside_range for part in parts),
        excluded_duplicates=sum(part.excluded_duplicates for part in parts),
    )


def normalize_evidence_payloads(
    payloads: Sequence[ProviderPayload],
    *,
    source_id: int,
    dividend_symbols: Sequence[str],
    global_symbols: Sequence[str],
    start_date: date,
    end_date: date,
    identities: Sequence[HistoricalEvidenceIdentity],
) -> NormalizedFinMindHistoricalEvidence:
    """Normalize dividend and global payloads against their correct universes."""

    parts: list[NormalizedFinMindHistoricalEvidence] = []
    dividend_payloads = tuple(
        payload for payload in payloads if payload.dataset == "dividend_results"
    )
    if dividend_payloads:
        parts.append(
            normalize_finmind_historical_evidence(
                dividend_payloads,
                source_id=source_id,
                symbols=dividend_symbols,
                start_date=start_date,
                end_date=end_date,
                identities=identities,
                expected_datasets={"dividend_results"},
            )
        )
    global_payloads = tuple(
        payload for payload in payloads if payload.dataset in GLOBAL_DATASETS
    )
    if global_payloads:
        parts.append(
            normalize_finmind_historical_evidence(
                global_payloads,
                source_id=source_id,
                symbols=global_symbols,
                start_date=start_date,
                end_date=end_date,
                identities=identities,
                expected_datasets=GLOBAL_DATASETS,
            )
        )
    return _merge_normalized(parts)
