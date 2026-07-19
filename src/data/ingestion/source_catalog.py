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


def fugle_data_source_row() -> dict[str, object]:
    """Return private server-side provenance for Fugle adjusted candles."""

    return {
        "source_code": "FUGLE",
        "display_name": "Fugle MarketData v1",
        "source_timezone": "Asia/Taipei",
        "revision_policy": "PAYLOAD_HASH_VERSIONED_RETRIEVED_AT_LOWER_BOUND",
        "is_active": True,
    }


def security_snapshot_source_rows() -> list[dict[str, object]]:
    """Derived rows bind MOPS identity data to exchange trading-state data."""

    return [
        {
            "source_code": f"{market}_MOPS_SNAPSHOT",
            "display_name": f"{market} + MOPS point-in-time security snapshot",
            "source_timezone": "Asia/Taipei",
            "revision_policy": "DAILY_COMPOSITE_HASH_FIRST_OBSERVATION",
            "is_active": True,
        }
        for market in ("TWSE", "TPEX")
    ]
