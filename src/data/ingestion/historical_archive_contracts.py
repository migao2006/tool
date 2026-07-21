"""Immutable contracts for research-only historical Parquet archives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import re

from src.data.providers.validation import require_path_segment
from src.data.providers.tpex import TPEX_MONTHLY_OHLC_DATASET
from src.data.providers.twse import TAIEX_MONTHLY_OHLC_DATASET

from .taiex_ohlc_contracts import TAIEX_OHLC_SCHEMA_VERSION
from .tpex_ohlc_contracts import TPEX_OHLC_SCHEMA_VERSION


HISTORICAL_ARCHIVE_SCHEMA_VERSION = "historical_daily_bars.v1"
HISTORICAL_ARCHIVE_COMPRESSION = "ZSTD"
HISTORICAL_ARCHIVE_CONTENT_TYPE = "application/vnd.apache.parquet"

HISTORICAL_ARCHIVE_SCHEMA_VERSIONS = {
    "daily_bars": HISTORICAL_ARCHIVE_SCHEMA_VERSION,
    "adjusted_bars": "historical_adjusted_bars.v1",
    "institutional_flows": "historical_institutional_flows.v1",
    "margin_short": "historical_margin_short.v1",
    "benchmark_total_return": "historical_benchmark_total_return.v1",
    TAIEX_MONTHLY_OHLC_DATASET: TAIEX_OHLC_SCHEMA_VERSION,
    TPEX_MONTHLY_OHLC_DATASET: TPEX_OHLC_SCHEMA_VERSION,
}

HISTORICAL_ARCHIVE_PROVIDER_DATASETS = {
    "FINMIND": frozenset(
        {
            "daily_bars",
            "adjusted_bars",
            "institutional_flows",
            "margin_short",
            "benchmark_total_return",
        }
    ),
    "TWSE": frozenset({TAIEX_MONTHLY_OHLC_DATASET}),
    "TPEX": frozenset({TPEX_MONTHLY_OHLC_DATASET}),
    "FUGLE": frozenset({"adjusted_bars"}),
}

_SCHEDULED_MARKETS = frozenset({"TWSE", "TPEX"})
_ASSET_TYPES = frozenset({"COMMON_STOCK", "ETF", "BENCHMARK"})
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
    source_dataset: str = "daily_bars"
    provider_code: str = "FINMIND"

    def __post_init__(self) -> None:
        scheduled_market = self.scheduled_market.strip().upper()
        asset_type = self.asset_type.strip().upper()
        source_symbol = require_path_segment(
            self.source_symbol,
            field="source_symbol",
        )
        source_dataset = require_path_segment(
            self.source_dataset,
            field="source_dataset",
        )
        provider_code = require_path_segment(
            self.provider_code,
            field="provider_code",
        ).upper()
        digest = self.source_payload_sha256.strip().lower()
        if scheduled_market not in _SCHEDULED_MARKETS:
            raise ValueError("scheduled_market must be TWSE or TPEX")
        if asset_type not in _ASSET_TYPES:
            raise ValueError("asset_type must be COMMON_STOCK, ETF, or BENCHMARK")
        if provider_code not in HISTORICAL_ARCHIVE_PROVIDER_DATASETS:
            raise ValueError("provider_code is not supported by the archive contract")
        if source_dataset not in HISTORICAL_ARCHIVE_PROVIDER_DATASETS[provider_code]:
            raise ValueError(
                "provider_code and source_dataset are not an allowed archive pair"
            )
        if provider_code == "FUGLE" and (
            scheduled_market != "TWSE" or asset_type != "COMMON_STOCK"
        ):
            raise ValueError(
                "FUGLE adjusted archives are limited to TWSE common stocks"
            )
        if provider_code == "TWSE" and (
            scheduled_market != "TWSE" or asset_type != "BENCHMARK"
        ):
            raise ValueError("TWSE index archives require the TWSE benchmark scope")
        if provider_code == "TPEX" and (
            scheduled_market != "TPEX" or asset_type != "BENCHMARK"
        ):
            raise ValueError("TPEX index archives require the TPEX benchmark scope")
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
        object.__setattr__(self, "source_dataset", source_dataset)
        object.__setattr__(self, "provider_code", provider_code)
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
        expected_schema = HISTORICAL_ARCHIVE_SCHEMA_VERSIONS[
            self.request.source_dataset
        ]
        if self.schema_version != expected_schema:
            raise ValueError("unsupported historical archive schema version")
        if self.compression != HISTORICAL_ARCHIVE_COMPRESSION:
            raise ValueError("historical archives must use ZSTD compression")
        if self.content_type != HISTORICAL_ARCHIVE_CONTENT_TYPE:
            raise ValueError("historical archives must use the Parquet content type")

    def object_metadata(self) -> dict[str, str]:
        """Return non-secret ASCII metadata suitable for an R2 object."""

        metadata = {
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
        # Preserve the immutable daily-bar object contract already stored in R2.
        # Supplemental schemas need the extra discriminator because they share
        # the generic archive writer.
        if self.request.source_dataset != "daily_bars":
            metadata["source-dataset"] = self.request.source_dataset
        if self.request.provider_code != "FINMIND":
            metadata["provider-code"] = self.request.provider_code
        return metadata
