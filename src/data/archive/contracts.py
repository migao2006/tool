"""Fail-closed contracts for reading one historical R2 archive object."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import re
from typing import cast

from src.data.ingestion.historical_archive_contracts import (
    HISTORICAL_ARCHIVE_SCHEMA_VERSION,
    HistoricalArchiveRequest,
)


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class HistoricalArchiveReadError(RuntimeError):
    """Stable archive-read failure that never includes credentials or row data."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code: str = reason_code


def _required_text(values: Mapping[str, object], name: str) -> str:
    value = values.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"manifest is missing {name}")
    return value.strip()


def _optional_text(values: Mapping[str, object], name: str) -> str | None:
    value = values.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"manifest contains an invalid {name}")
    return value.strip()


def _positive_integer(values: Mapping[str, object], name: str) -> int:
    value = values.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"manifest contains an invalid {name}")
    return value


def _nonnegative_integer(values: Mapping[str, object], name: str) -> int:
    value = values.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"manifest contains an invalid {name}")
    return value


def _date_value(values: Mapping[str, object], name: str) -> date:
    value = values.get(name)
    if type(value) is date:
        return value
    if not isinstance(value, str):
        raise ValueError(f"manifest contains an invalid {name}")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"manifest contains an invalid {name}") from error


def _datetime_value(values: Mapping[str, object], name: str) -> datetime:
    value = values.get(name)
    try:
        parsed = (
            value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        )
    except ValueError as error:
        raise ValueError(f"manifest contains an invalid {name}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"manifest contains a timezone-naive {name}")
    return parsed.astimezone(timezone.utc)


def _reason_codes(values: Mapping[str, object]) -> tuple[str, ...]:
    value = values.get("reason_codes")
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("manifest contains invalid reason_codes")
    raw_codes = cast(Sequence[object], value)
    if any(not isinstance(code, str) or not code for code in raw_codes):
        raise ValueError("manifest contains invalid reason_codes")
    return tuple(cast(str, code) for code in raw_codes)


@dataclass(frozen=True)
class HistoricalArchiveManifest:
    """Integrity-bearing subset of ``historical_archive_objects``."""

    archive_key: str
    storage_provider: str
    bucket_name: str
    object_key: str
    object_etag: str | None
    schema_version: str
    provider_code: str
    source_dataset: str
    source_version: str
    source_symbol: str
    scheduled_market: str
    asset_type: str
    requested_start_date: date
    requested_end_date: date
    min_trade_date: date
    max_trade_date: date
    source_payload_hash: str
    parquet_sha256: str
    byte_size: int
    row_count: int
    parsed_row_count: int
    quarantined_row_count: int
    first_observed_at: datetime
    point_in_time_status: str
    usage_scope: str
    system_status: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        expected_key = sha256(
            f"{self.bucket_name}\0{self.object_key}".encode("utf-8")
        ).hexdigest()
        if self.archive_key != expected_key:
            raise ValueError("archive_key does not match the object location")
        if self.storage_provider != "CLOUDFLARE_R2":
            raise ValueError("storage_provider must be CLOUDFLARE_R2")
        if self.schema_version != HISTORICAL_ARCHIVE_SCHEMA_VERSION:
            raise ValueError("unsupported historical archive schema version")
        if self.provider_code != "FINMIND" or self.source_dataset != "daily_bars":
            raise ValueError("unsupported historical archive source")
        if not self.source_version:
            raise ValueError("source_version must not be empty")
        if not _SHA256_PATTERN.fullmatch(self.parquet_sha256):
            raise ValueError("parquet_sha256 must be a SHA-256 hex digest")
        if self.byte_size <= 0 or self.row_count <= 0:
            raise ValueError("archive byte and row counts must be positive")
        if self.parsed_row_count < 0 or self.quarantined_row_count < 0:
            raise ValueError("archive parse counts must not be negative")
        if self.parsed_row_count + self.quarantined_row_count != self.row_count:
            raise ValueError("archive parse counts do not match row_count")
        if not (
            self.requested_start_date
            <= self.min_trade_date
            <= self.max_trade_date
            <= self.requested_end_date
        ):
            raise ValueError("manifest trade-date bounds are inconsistent")
        if (
            self.point_in_time_status != "UNVERIFIED"
            or self.usage_scope != "RAW_LANDING_ONLY"
            or self.system_status != "RESEARCH_ONLY"
        ):
            raise ValueError("archive manifest exceeds the allowed research-only scope")
        if not self.reason_codes:
            raise ValueError("reason_codes must not be empty")
        if self.object_etag is not None and not self.object_etag.strip():
            raise ValueError("object_etag must not be blank")

        # Reuse the writer-side request contract for market, asset, symbol,
        # requested dates, payload digest, and timezone validation.
        _ = HistoricalArchiveRequest(
            scheduled_market=self.scheduled_market,
            asset_type=self.asset_type,
            source_symbol=self.source_symbol,
            requested_start_date=self.requested_start_date,
            requested_end_date=self.requested_end_date,
            source_payload_sha256=self.source_payload_hash,
            retrieved_at=self.first_observed_at,
        )

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, object],
    ) -> "HistoricalArchiveManifest":
        """Parse a Supabase manifest row without accepting implicit defaults."""

        try:
            return cls(
                archive_key=_required_text(values, "archive_key").lower(),
                storage_provider=_required_text(values, "storage_provider"),
                bucket_name=_required_text(values, "bucket_name"),
                object_key=_required_text(values, "object_key"),
                object_etag=_optional_text(values, "object_etag"),
                schema_version=_required_text(values, "schema_version"),
                provider_code=_required_text(values, "provider_code"),
                source_dataset=_required_text(values, "source_dataset"),
                source_version=_required_text(values, "source_version"),
                source_symbol=_required_text(values, "source_symbol"),
                scheduled_market=_required_text(values, "scheduled_market"),
                asset_type=_required_text(values, "asset_type"),
                requested_start_date=_date_value(values, "requested_start_date"),
                requested_end_date=_date_value(values, "requested_end_date"),
                min_trade_date=_date_value(values, "min_trade_date"),
                max_trade_date=_date_value(values, "max_trade_date"),
                source_payload_hash=_required_text(
                    values, "source_payload_hash"
                ).lower(),
                parquet_sha256=_required_text(values, "parquet_sha256").lower(),
                byte_size=_positive_integer(values, "byte_size"),
                row_count=_positive_integer(values, "row_count"),
                parsed_row_count=_nonnegative_integer(values, "parsed_row_count"),
                quarantined_row_count=_nonnegative_integer(
                    values, "quarantined_row_count"
                ),
                first_observed_at=_datetime_value(values, "first_observed_at"),
                point_in_time_status=_required_text(values, "point_in_time_status"),
                usage_scope=_required_text(values, "usage_scope"),
                system_status=_required_text(values, "system_status"),
                reason_codes=_reason_codes(values),
            )
        except (TypeError, ValueError) as error:
            raise HistoricalArchiveReadError(
                "HISTORICAL_ARCHIVE_MANIFEST_INVALID",
                "The historical archive manifest is incomplete or inconsistent",
            ) from error


@dataclass(frozen=True)
class VerifiedHistoricalArchive:
    """Rows released only after manifest, R2, and Parquet verification succeeds."""

    manifest: HistoricalArchiveManifest
    rows: tuple[Mapping[str, object], ...]
    content_sha256: str
    byte_size: int
    row_count: int
    schema_version: str
    reason_codes: tuple[str, ...] = ()
