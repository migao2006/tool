"""Deterministic, non-overlapping FinMind evidence symbol scheduling."""

from __future__ import annotations

from collections.abc import Sequence

from .contracts import IngestionError
from .finmind_historical_evidence_contracts import HistoricalEvidenceIdentity


def verified_twse_symbols(
    identities: Sequence[HistoricalEvidenceIdentity],
) -> tuple[str, ...]:
    """Return a stable unique TWSE common-stock symbol catalog."""

    symbols = tuple(sorted({identity.source_symbol for identity in identities}))
    if not symbols:
        raise IngestionError(
            "FINMIND_HISTORICAL_IDENTITY_CATALOG_EMPTY",
            "no verified TWSE common-stock identities are available",
        )
    return symbols


def select_symbol_batch(
    identities: Sequence[HistoricalEvidenceIdentity],
    *,
    shard_index: int,
    shard_count: int,
    batch_index: int,
    max_symbols: int,
) -> tuple[str, ...]:
    """Select one rotating batch; separate credential shards never overlap."""

    if isinstance(shard_count, bool) or shard_count <= 0:
        raise ValueError("shard_count must be positive")
    if isinstance(shard_index, bool) or not 0 <= shard_index < shard_count:
        raise ValueError("shard_index must be within shard_count")
    if isinstance(batch_index, bool) or batch_index < 0:
        raise ValueError("batch_index must be non-negative")
    if isinstance(max_symbols, bool) or not 1 <= max_symbols <= 20:
        raise ValueError("max_symbols must be between 1 and 20")

    shard = verified_twse_symbols(identities)[shard_index::shard_count]
    if not shard:
        raise IngestionError(
            "FINMIND_HISTORICAL_SHARD_EMPTY",
            "the requested credential shard contains no symbols",
        )
    if len(shard) <= max_symbols:
        return shard

    start = (batch_index * max_symbols) % len(shard)
    stop = start + max_symbols
    if stop <= len(shard):
        return shard[start:stop]
    return (*shard[start:], *shard[: stop - len(shard)])
