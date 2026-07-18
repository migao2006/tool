"""Deterministic, traversal-safe object keys for historical archives."""

from __future__ import annotations

from .historical_archive_contracts import HistoricalArchiveRequest


_ARCHIVE_PREFIX = ("raw", "v1", "provider=finmind", "dataset=daily_bars")


def build_historical_object_key(request: HistoricalArchiveRequest) -> str:
    """Build a stable key without asserting a resolved security market.

    Every dynamic segment has already passed strict path-segment, enum, date,
    or SHA-256 validation in ``HistoricalArchiveRequest``.
    """

    return "/".join(
        (
            *_ARCHIVE_PREFIX,
            f"scheduled_market={request.scheduled_market}",
            f"asset_type={request.asset_type}",
            f"symbol={request.source_symbol}",
            f"request_start={request.requested_start_date.isoformat()}",
            f"request_end={request.requested_end_date.isoformat()}",
            f"payload_sha256={request.source_payload_sha256}.parquet",
        )
    )
