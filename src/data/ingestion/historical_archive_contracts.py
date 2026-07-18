"""Immutable contracts for research-only historical Parquet archives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import re

from src.data.providers.validation import require_path_segment


HISTORICAL_ARCHIVE_SCHEMA_VERSION = "historical_daily_bars.v1"
HISTORICAL_ARCHIVE_COMPRESSION = "ZSTD"
HISTORICAL_ARCHIVE_CONTENT_TYPE = "application/vnd.apache.parquet"

_SCHEDULED_MARKETS = frozenset({"TWSE", "TPEX"})
_ASSET_TYPES = frozenset({"COMMON_STOCK", "ETF"})
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class HistoricalArchiveRequest:
    """Identity of one source response being archived.

    ``scheduled_market`` is only the queue/universe venue used to schedule the
    request. It must never be interpreted as a resolved point-in-time security
    market or copied into ``source_market_claim``.
    """

    scheduled_market: str
    asset_type: str
    source_symbol: str
    requested_start_date: date
    requested_end_date: date
    source_payload_sha256: str
    retrieved_at: datetime

    def __post_init__(self) -> None:
        scheduled_market = self.scheduled_market.strip().upper()
        asset_type = self.asset_type.strip().upper()
        source_symbol = require_path_segment(
            self.source_symbol,
            field="source_symbol",
        )
        digest = self.source_payload_sha256.strip().lower()
        if scheduled_market not in _SCHEDULED_MARKETS:
            raise ValueError("scheduled_market must be TWSE or TPEX")
        if asset_type not in _ASSET_TYPES:
            raise ValueError("asset_type must be COMMON_STOCK or ETF")
        if (
            type(self.requested_start_date) is not date
            or type(self.requested_end_date) is not date
        ):
            raise TypeError("requested dates must be date values")
        if self.requested_start_date > self.requested_end_date:
            raise ValueError(
                "requested_start_date must not be after requested_end_date"
            )
        if not _SHA256_PATTERN.fullmatch(digest):
            raise ValueError("source_payload_sha256 must be a SHA-256 hex digest")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")

        object.__setattr__(self, "scheduled_market", scheduled_market)
        object.__setattr__(self, "asset_type", asset_type)
        object.__setattr__(self, "source_symbol", source_symbol)
        object.__setattr__(self, "source_payload_sha256", digest)
        object.__setattr__(
            self,
            "retrieved_at",
            self.retrieved_at.astimezone(timezone.utc),
        )


@dataclass(frozen=True)
class HistoricalArchiveArtifact:
    """Parquet bytes plus integrity and upload metadata."""

    request: HistoricalArchiveRequest
    object_key: str
    payload: bytes
    content_sha256: str
    byte_size: int
    row_count: int
    schema_version: str = HISTORICAL_ARCHIVE_SCHEMA_VERSION
    compression: str = HISTORICAL_ARCHIVE_COMPRESSION
    content_type: str = HISTORICAL_ARCHIVE_CONTENT_TYPE

    def __post_init__(self) -> None:
        if not self.object_key or self.object_key.startswith(("/", "\\")):
            raise ValueError("object_key must be a relative object key")
        if ".." in self.object_key.split("/") or "\\" in self.object_key:
            raise ValueError("object_key must not contain traversal segments")
        if self.byte_size != len(self.payload):
            raise ValueError("byte_size does not match payload")
        if self.row_count <= 0:
            raise ValueError("row_count must be positive")
        actual_digest = sha256(self.payload).hexdigest()
        if self.content_sha256 != actual_digest:
            raise ValueError("content_sha256 does not match payload")
        if self.schema_version != HISTORICAL_ARCHIVE_SCHEMA_VERSION:
            raise ValueError("unsupported historical archive schema version")
        if self.compression != HISTORICAL_ARCHIVE_COMPRESSION:
            raise ValueError("historical archives must use ZSTD compression")
        if self.content_type != HISTORICAL_ARCHIVE_CONTENT_TYPE:
            raise ValueError("historical archives must use the Parquet content type")

    def object_metadata(self) -> dict[str, str]:
        """Return non-secret ASCII metadata suitable for an R2 object."""

        return {
            "content-sha256": self.content_sha256,
            "byte-size": str(self.byte_size),
            "row-count": str(self.row_count),
            "schema-version": self.schema_version,
            "compression": self.compression.lower(),
            "scheduled-market": self.request.scheduled_market,
            "asset-type": self.request.asset_type,
            "source-payload-sha256": self.request.source_payload_sha256,
            "retrieved-at": self.request.retrieved_at.isoformat(),
        }
