from dataclasses import replace

import pytest

from src.data.ingestion.finmind_historical_evidence_schedule import (
    select_symbol_batch,
    verified_twse_symbols,
)
from tests.support.finmind_historical_evidence_fixtures import identity


def _identities(count: int = 30):
    template = identity()
    return tuple(
        replace(
            template,
            listing_evidence_id=index,
            listing_period_id=f"TWSE:{1000 + index}:2000-01-01",
            security_id=1000 + index,
            source_symbol=str(1000 + index),
        )
        for index in range(1, count + 1)
    )


def test_three_credential_shards_are_stable_and_non_overlapping() -> None:
    identities = _identities()
    batches = [
        select_symbol_batch(
            identities,
            shard_index=index,
            shard_count=3,
            batch_index=0,
            max_symbols=10,
        )
        for index in range(3)
    ]

    assert len(set().union(*map(set, batches))) == 30
    assert all(set(left).isdisjoint(right) for left, right in zip(batches, batches[1:]))


def test_batch_rotation_wraps_without_duplicates() -> None:
    rows = _identities(11)
    selected = select_symbol_batch(
        rows,
        shard_index=0,
        shard_count=1,
        batch_index=2,
        max_symbols=5,
    )

    assert len(selected) == 5
    assert len(set(selected)) == 5
    assert selected == ("1011", "1001", "1002", "1003", "1004")


def test_symbol_catalog_rejects_empty_identity_state() -> None:
    with pytest.raises(Exception) as captured:
        verified_twse_symbols(())

    assert getattr(captured.value, "reason_code", None) == (
        "FINMIND_HISTORICAL_IDENTITY_CATALOG_EMPTY"
    )
