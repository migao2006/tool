"""Read and validate paginated R2 archive manifests from Supabase."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Protocol, final

from .contracts import HistoricalArchiveManifest, HistoricalArchiveReadError


_MANIFEST_FIELDS = (
    "archive_id",
    "archive_key",
    "storage_provider",
    "bucket_name",
    "object_key",
    "object_etag",
    "schema_version",
    "provider_code",
    "source_dataset",
    "source_version",
    "source_symbol",
    "scheduled_market",
    "asset_type",
    "requested_start_date",
    "requested_end_date",
    "min_trade_date",
    "max_trade_date",
    "source_payload_hash",
    "parquet_sha256",
    "byte_size",
    "row_count",
    "parsed_row_count",
    "quarantined_row_count",
    "first_observed_at",
    "point_in_time_status",
    "usage_scope",
    "system_status",
    "reason_codes",
)


class ManifestRowSource(Protocol):
    """Minimal private-schema query boundary used by the repository."""

    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class HistoricalArchiveManifestSnapshot:
    """Deterministic set of validated manifest rows used by one audit."""

    rows: tuple[Mapping[str, object], ...]
    snapshot_sha256: str
    complete: bool
    high_water_archive_id: int | None = None

    @property
    def object_count(self) -> int:
        return len(self.rows)


def _canonical_manifest_mapping(
    archive_id: int,
    manifest: HistoricalArchiveManifest,
) -> dict[str, object]:
    return {"archive_id": archive_id, **asdict(manifest)}


def _snapshot_identity(values: Mapping[str, object]) -> str:
    """Hash the same canonical mapping consumed by downstream audits."""

    def serialize(value: object) -> str:
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        raise TypeError(f"unsupported manifest value: {type(value).__name__}")

    return json.dumps(
        values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=serialize,
    )


@final
class HistoricalArchiveManifestRepository:
    """Keyset-page manifests without relying on a mutable row offset."""

    def __init__(self, source: ManifestRowSource, *, page_size: int = 500) -> None:
        if not 1 <= page_size <= 1_000:
            raise ValueError("page_size must be between 1 and 1000")
        self.source = source
        self.page_size = page_size

    def fetch(
        self,
        *,
        max_objects: int | None = None,
        filters: Mapping[str, str] | None = None,
        through_archive_id: int | None = None,
    ) -> HistoricalArchiveManifestSnapshot:
        if max_objects is not None and max_objects <= 0:
            raise ValueError("max_objects must be positive when provided")
        if through_archive_id is not None and through_archive_id < 0:
            raise ValueError("through_archive_id must not be negative")

        fixed_filters = dict(filters or {})
        if {"archive_id", "order"}.intersection(fixed_filters):
            raise ValueError("manifest filters cannot override keyset pagination")

        rows: list[Mapping[str, object]] = []
        identities: list[str] = []
        last_archive_id = 0
        complete = True
        high_water_archive_id = through_archive_id
        high_water_page: list[dict[str, object]] = []
        if through_archive_id is None:
            high_water_page = self.source.select_rows(
                "historical_archive_objects",
                select="archive_id",
                filters={**fixed_filters, "order": "archive_id.desc"},
                limit=1,
            )
        if len(high_water_page) > 1:
            raise HistoricalArchiveReadError(
                "HISTORICAL_ARCHIVE_MANIFEST_PAGE_INVALID",
                "Supabase returned more high-water rows than requested",
            )
        if high_water_page:
            candidate = high_water_page[0].get("archive_id")
            if (
                isinstance(candidate, bool)
                or not isinstance(candidate, int)
                or candidate <= 0
            ):
                raise HistoricalArchiveReadError(
                    "HISTORICAL_ARCHIVE_MANIFEST_ORDER_INVALID",
                    "Archive manifest high-water archive_id is invalid",
                )
            high_water_archive_id = candidate

        reached_high_water = False
        while high_water_archive_id is not None:
            remaining = None if max_objects is None else max_objects - len(rows)
            if remaining is not None and remaining <= 0:
                complete = False
                break
            request_limit = (
                self.page_size if remaining is None else min(self.page_size, remaining)
            )
            page = self.source.select_rows(
                "historical_archive_objects",
                select=",".join(_MANIFEST_FIELDS),
                filters={
                    **fixed_filters,
                    "archive_id": f"gt.{last_archive_id}",
                    "order": "archive_id.asc",
                },
                limit=request_limit,
            )
            if len(page) > request_limit:
                raise HistoricalArchiveReadError(
                    "HISTORICAL_ARCHIVE_MANIFEST_PAGE_INVALID",
                    "Supabase returned more archive manifests than requested",
                )
            if not page:
                break

            for raw in page:
                archive_id = raw.get("archive_id")
                if (
                    isinstance(archive_id, bool)
                    or not isinstance(archive_id, int)
                    or archive_id <= last_archive_id
                ):
                    raise HistoricalArchiveReadError(
                        "HISTORICAL_ARCHIVE_MANIFEST_ORDER_INVALID",
                        "Archive manifests are not strictly ordered by archive_id",
                    )
                if archive_id > high_water_archive_id:
                    reached_high_water = True
                    break
                manifest = HistoricalArchiveManifest.from_mapping(raw)
                last_archive_id = archive_id
                canonical = _canonical_manifest_mapping(archive_id, manifest)
                rows.append(MappingProxyType(canonical))
                identities.append(_snapshot_identity(canonical))

            if (
                reached_high_water
                or last_archive_id >= high_water_archive_id
                or len(page) < request_limit
            ):
                break

        digest = sha256("\n".join(identities).encode("utf-8")).hexdigest()
        return HistoricalArchiveManifestSnapshot(
            rows=tuple(rows),
            snapshot_sha256=digest,
            complete=complete,
            high_water_archive_id=high_water_archive_id,
        )
