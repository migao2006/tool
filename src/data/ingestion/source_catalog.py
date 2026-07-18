"""Stable source metadata used by historical ingestion jobs."""

from __future__ import annotations


def finmind_data_source_row() -> dict[str, object]:
    """Return a fresh row so callers cannot mutate shared source metadata."""

    return {
        "source_code": "FINMIND",
        "display_name": "FinMind API v4",
        "source_timezone": "Asia/Taipei",
        "revision_policy": "PAYLOAD_HASH_VERSIONED_RETRIEVED_AT_LOWER_BOUND",
        "is_active": True,
    }
