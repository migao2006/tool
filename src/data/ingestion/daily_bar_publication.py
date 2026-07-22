"""Publish one immutable current daily-bar snapshot per market to Cloudflare R2."""

from __future__ import annotations

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
from math import isfinite
import os
import re
import sys
from typing import Any, Protocol, final

from src.data.daily_bar_publication_contracts import (
    DAILY_BAR_PUBLICATION_CONTENT_TYPE,
    DAILY_BAR_PUBLICATION_SCHEMA_VERSION,
    DailyBarPublicationSourceRow,
    DailyBarPublicationSourceSnapshot,
)
from src.data.object_storage.r2_client import ObjectMetadata, R2Client

from .contracts import IngestionError


MIN_COMMON_STOCK_ROWS_PER_MARKET = 500
_MARKETS = frozenset({"TWSE", "TPEX"})
_SOURCE_URLS = {
    "TWSE": "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
    "TPEX": "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
}


class DailyBarPublicationWriter(Protocol):
    def upsert(
        self,
        table: str,
        rows: Sequence[Mapping[str, object]],
        *,
        on_conflict: str,
        select: str | None = None,
        return_rows: bool = False,
        preserve_existing: bool = False,
    ) -> list[dict[str, object]]: ...

    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
        offset: int = 0,
    ) -> list[dict[str, object]]: ...

    def select_all_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        page_size: int = 1_000,
        max_rows: int = 10_000,
    ) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class DailyBarPublicationArtifact:
    snapshot: DailyBarPublicationSourceSnapshot
    object_key: str
    payload: bytes
    parquet_sha256: str
    byte_size: int
    row_count: int

    def __post_init__(self) -> None:
        if (
            self.byte_size != len(self.payload)
            or self.row_count != len(self.snapshot.rows)
            or self.row_count <= 0
            or sha256(self.payload).hexdigest() != self.parquet_sha256
        ):
            raise ValueError("daily-bar publication artifact integrity is invalid")

    def object_metadata(self) -> dict[str, str]:
        return {
            "schema-version": DAILY_BAR_PUBLICATION_SCHEMA_VERSION,
            "market": self.snapshot.market,
            "asset-type": "COMMON_STOCK",
            "trading-date": self.snapshot.trading_date.isoformat(),
            "row-count": str(self.row_count),
            "byte-size": str(self.byte_size),
            "parquet-sha256": self.parquet_sha256,
            "normalized-content-sha256": self.snapshot.normalized_content_sha256,
            "available-at": self.snapshot.first_observed_at.astimezone(timezone.utc).isoformat(),
        }


@dataclass(frozen=True)
class DailyBarPublicationResult:
    market: str
    trading_date: date
    publication_snapshot_id: int
    snapshot_key: str
    object_key: str
    created: bool
    parquet_sha256: str
    normalized_content_sha256: str
    row_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "market": self.market,
            "trading_date": self.trading_date.isoformat(),
            "publication_snapshot_id": self.publication_snapshot_id,
            "snapshot_key": self.snapshot_key,
            "object_key": self.object_key,
            "created": self.created,
            "parquet_sha256": self.parquet_sha256,
            "normalized_content_sha256": self.normalized_content_sha256,
            "row_count": self.row_count,
        }


def _positive_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a positive integer")
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a positive integer") from error
    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return parsed


def _optional_float(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    parsed = float(str(value))
    if not isfinite(parsed):
        raise ValueError("daily-bar numeric value is not finite")
    return parsed


def _optional_integer(value: object) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, bool):
        raise ValueError("daily-bar integer value is invalid")
    return int(str(value))


def _aware_datetime(value: object, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} is not a valid timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _canonical_hash(rows: Sequence[DailyBarPublicationSourceRow]) -> str:
    encoded = json.dumps(
        [row.canonical_mapping() for row in rows],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


@final
class DailyBarPublicationSourceRepository:
    """Read one complete market/date snapshot from private current daily bars."""

    def __init__(self, writer: DailyBarPublicationWriter) -> None:
        self.writer = writer

    def fetch(
        self,
        *,
        market: str,
        trading_date: date,
    ) -> DailyBarPublicationSourceSnapshot:
        normalized_market = market.strip().upper()
        if normalized_market not in _MARKETS:
            raise ValueError("market must be TWSE or TPEX")
        sources = self.writer.select_rows(
            "data_sources",
            select="source_id,source_code",
            filters={"source_code": f"eq.{normalized_market}"},
            limit=2,
        )
        if len(sources) != 1:
            raise IngestionError(
                "DAILY_BAR_PUBLICATION_SOURCE_MISSING",
                "The official daily-bar data source could not be identified",
            )
        source_id = _positive_integer(sources[0].get("source_id"), "source_id")
        raw_rows = self.writer.select_all_rows(
            "daily_bars",
            select=(
                "daily_bar_id,security_id,trade_date,raw_open,raw_high,raw_low,"
                "raw_close,volume_shares,turnover_ntd,trade_count,source_id,"
                "source_version,available_at,"
                "securities!inner(symbol,market,asset_type)"
            ),
            filters={
                "trade_date": f"eq.{trading_date.isoformat()}",
                "source_id": f"eq.{source_id}",
                "securities.market": f"eq.{normalized_market}",
                "securities.asset_type": "eq.COMMON_STOCK",
                "order": "security_id.asc,available_at.desc,daily_bar_id.desc",
            },
            page_size=1_000,
            max_rows=5_000,
        )
        selected: dict[int, DailyBarPublicationSourceRow] = {}
        for raw in raw_rows:
            identity = raw.get("securities")
            if not isinstance(identity, Mapping):
                raise IngestionError(
                    "DAILY_BAR_PUBLICATION_IDENTITY_MISSING",
                    "A daily bar is missing its security identity",
                )
            security_id = _positive_integer(raw.get("security_id"), "security_id")
            if security_id in selected:
                continue
            row_market = str(identity.get("market") or "").strip().upper()
            asset_type = str(identity.get("asset_type") or "").strip().upper()
            symbol = str(identity.get("symbol") or "").strip()
            if row_market != normalized_market or asset_type != "COMMON_STOCK":
                raise IngestionError(
                    "DAILY_BAR_PUBLICATION_SCOPE_MISMATCH",
                    "A daily bar is outside the requested market scope",
                )
            try:
                row_date = date.fromisoformat(str(raw.get("trade_date") or ""))
                row = DailyBarPublicationSourceRow(
                    daily_bar_id=_positive_integer(raw.get("daily_bar_id"), "daily_bar_id"),
                    security_id=security_id,
                    symbol=symbol,
                    market=row_market,
                    trade_date=row_date,
                    open_price=_optional_float(raw.get("raw_open")),
                    high_price=_optional_float(raw.get("raw_high")),
                    low_price=_optional_float(raw.get("raw_low")),
                    close_price=_optional_float(raw.get("raw_close")),
                    trading_volume=_optional_float(raw.get("volume_shares")),
                    trading_value=_optional_float(raw.get("turnover_ntd")),
                    trade_count=_optional_integer(raw.get("trade_count")),
                    source_id=_positive_integer(raw.get("source_id"), "source_id"),
                    source_version=str(raw.get("source_version") or "").strip(),
                    available_at=_aware_datetime(raw.get("available_at"), "available_at"),
                )
            except (TypeError, ValueError) as error:
                raise IngestionError(
                    "DAILY_BAR_PUBLICATION_ROW_INVALID",
                    "A current daily bar cannot satisfy the publication contract",
                ) from error
            selected[security_id] = row
        rows = tuple(sorted(selected.values(), key=lambda row: row.symbol))
        if len(rows) < MIN_COMMON_STOCK_ROWS_PER_MARKET:
            raise IngestionError(
                "DAILY_BAR_PUBLICATION_COVERAGE_TOO_LOW",
                "The current daily-bar snapshot is below minimum market coverage",
            )
        if any(row.trade_date != trading_date for row in rows):
            raise IngestionError(
                "DAILY_BAR_PUBLICATION_DATE_MISMATCH",
                "The current daily-bar snapshot contains another trading date",
            )
        return DailyBarPublicationSourceSnapshot(
            market=normalized_market,
            trading_date=trading_date,
            rows=rows,
            source_id=source_id,
            source_url=_SOURCE_URLS[normalized_market],
            source_versions=tuple(sorted({row.source_version for row in rows})),
            first_observed_at=max(row.available_at for row in rows),
            normalized_content_sha256=_canonical_hash(rows),
        )


def _pyarrow_modules() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ModuleNotFoundError as error:
        raise IngestionError(
            "PARQUET_DEPENDENCY_MISSING",
            "pyarrow is required to publish current daily bars",
        ) from error
    return pa, pq


def _publication_schema(snapshot: DailyBarPublicationSourceSnapshot) -> Any:
    pa, _ = _pyarrow_modules()
    return pa.schema(
        [
            pa.field("daily_bar_id", pa.int64(), nullable=False),
            pa.field("security_id", pa.int64(), nullable=False),
            pa.field("symbol", pa.string(), nullable=False),
            pa.field("market", pa.string(), nullable=False),
            pa.field("asset_type", pa.string(), nullable=False),
            pa.field("trade_date", pa.date32(), nullable=False),
            pa.field("open_price", pa.float64()),
            pa.field("high_price", pa.float64()),
            pa.field("low_price", pa.float64()),
            pa.field("close_price", pa.float64()),
            pa.field("trading_volume", pa.float64()),
            pa.field("trading_value", pa.float64()),
            pa.field("trade_count", pa.int64()),
            pa.field("source_id", pa.int64(), nullable=False),
            pa.field("source_version", pa.string(), nullable=False),
            pa.field("available_at", pa.timestamp("us", tz="UTC"), nullable=False),
        ],
        metadata={
            b"publication.schema_version": DAILY_BAR_PUBLICATION_SCHEMA_VERSION.encode("ascii"),
            b"publication.market": snapshot.market.encode("ascii"),
            b"publication.asset_type": b"COMMON_STOCK",
            b"publication.trading_date": snapshot.trading_date.isoformat().encode("ascii"),
            b"publication.normalized_content_sha256": (
                snapshot.normalized_content_sha256.encode("ascii")
            ),
            b"publication.available_at": snapshot.first_observed_at.astimezone(timezone.utc)
            .isoformat()
            .encode("ascii"),
            b"publication.row_count": str(len(snapshot.rows)).encode("ascii"),
            b"publication.system_status": b"RESEARCH_ONLY",
        },
    )


def serialize_daily_bar_publication(
    snapshot: DailyBarPublicationSourceSnapshot,
) -> DailyBarPublicationArtifact:
    pa, pq = _pyarrow_modules()
    sink = pa.BufferOutputStream()
    table = pa.Table.from_pylist(
        [row.parquet_mapping() for row in snapshot.rows],
        schema=_publication_schema(snapshot),
    )
    pq.write_table(
        table,
        sink,
        compression="zstd",
        compression_level=9,
        version="2.6",
        data_page_version="2.0",
        use_dictionary=True,
        write_statistics=True,
    )
    payload = sink.getvalue().to_pybytes()
    digest = sha256(payload).hexdigest()
    object_key = (
        "current/v1/"
        f"market={snapshot.market}/asset_type=COMMON_STOCK/"
        f"trading_date={snapshot.trading_date.isoformat()}/"
        f"normalized_sha256={snapshot.normalized_content_sha256}/"
        f"parquet_sha256={digest}.parquet"
    )
    return DailyBarPublicationArtifact(
        snapshot=snapshot,
        object_key=object_key,
        payload=payload,
        parquet_sha256=digest,
        byte_size=len(payload),
        row_count=len(snapshot.rows),
    )


def _git_commit() -> str | None:
    value = os.environ.get("GITHUB_SHA", "").strip().lower()
    return value if re.fullmatch(r"[0-9a-f]{7,40}", value) else None


def _library_versions() -> dict[str, str]:
    result = {"python": sys.version.split()[0]}
    for package in ("pyarrow", "boto3"):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            continue
    return result


def _verified_head(
    store: R2Client,
    artifact: DailyBarPublicationArtifact,
    *,
    created: bool,
) -> ObjectMetadata:
    head = store.head(artifact.object_key)
    if head is None:
        raise IngestionError(
            "DAILY_BAR_PUBLICATION_OBJECT_MISSING",
            "R2 did not return the current daily-bar snapshot after upload",
        )
    expected = artifact.object_metadata()
    if (
        head.content_length != artifact.byte_size
        or head.content_type != DAILY_BAR_PUBLICATION_CONTENT_TYPE
        or any(head.metadata.get(name) != value for name, value in expected.items())
    ):
        raise IngestionError(
            "DAILY_BAR_PUBLICATION_METADATA_INVALID",
            "The R2 daily-bar publication metadata is inconsistent",
        )
    if not created:
        existing = store.get(artifact.object_key)
        if sha256(existing).hexdigest() != artifact.parquet_sha256:
            raise IngestionError(
                "DAILY_BAR_PUBLICATION_INTEGRITY_MISMATCH",
                "The existing R2 daily-bar publication failed checksum verification",
            )
    return head


@final
class DailyBarPublicationManifestRepository:
    def __init__(self, writer: DailyBarPublicationWriter) -> None:
        self.writer = writer

    def save_and_read(self, manifest: Mapping[str, object]) -> dict[str, object]:
        _ = self.writer.upsert(
            "daily_bar_publication_snapshots",
            [manifest],
            on_conflict="snapshot_key",
            preserve_existing=True,
        )
        rows = self.writer.select_rows(
            "daily_bar_publication_snapshots",
            select=(
                "publication_snapshot_id,snapshot_key,storage_provider,bucket_name,"
                "object_key,object_etag,schema_version,parquet_sha256,"
                "normalized_content_sha256,byte_size,row_count,market,asset_type,"
                "trading_date,provider_code,source_id,source_dataset,source_event_id,"
                "source_version,source_revision_hash,source_payload_hash,source_url,"
                "source_metadata,published_at,first_observed_at,available_at,"
                "available_at_basis,verification_status,usage_scope,system_status,"
                "reason_codes,git_commit,library_versions,ingested_at"
            ),
            filters={"snapshot_key": f"eq.{manifest['snapshot_key']}"},
            limit=2,
        )
        if len(rows) != 1:
            raise IngestionError(
                "DAILY_BAR_PUBLICATION_MANIFEST_READ_FAILED",
                "The saved daily-bar publication manifest could not be read back",
            )
        return rows[0]


@final
class DailyBarPublicationService:
    def __init__(
        self,
        *,
        store: R2Client,
        repository: DailyBarPublicationManifestRepository,
    ) -> None:
        self.store = store
        self.repository = repository

    def publish(
        self,
        snapshot: DailyBarPublicationSourceSnapshot,
    ) -> DailyBarPublicationResult:
        artifact = serialize_daily_bar_publication(snapshot)
        try:
            created = self.store.put_if_absent(
                artifact.object_key,
                artifact.payload,
                content_type=DAILY_BAR_PUBLICATION_CONTENT_TYPE,
                metadata=artifact.object_metadata(),
            )
        except Exception as error:
            raise IngestionError(
                "DAILY_BAR_PUBLICATION_R2_WRITE_FAILED",
                "The current daily-bar snapshot could not be written to R2",
            ) from error
        head = _verified_head(self.store, artifact, created=created)
        snapshot_key = sha256(
            f"{self.store.bucket_name}\0{artifact.object_key}".encode("utf-8")
        ).hexdigest()
        source_revision_hash = sha256(
            json.dumps(
                {
                    "market": snapshot.market,
                    "source_versions": snapshot.source_versions,
                    "normalized_content_sha256": snapshot.normalized_content_sha256,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        manifest = {
            "snapshot_key": snapshot_key,
            "storage_provider": "CLOUDFLARE_R2",
            "bucket_name": self.store.bucket_name,
            "object_key": artifact.object_key,
            "object_etag": head.etag,
            "schema_version": DAILY_BAR_PUBLICATION_SCHEMA_VERSION,
            "parquet_sha256": artifact.parquet_sha256,
            "normalized_content_sha256": snapshot.normalized_content_sha256,
            "byte_size": artifact.byte_size,
            "row_count": artifact.row_count,
            "market": snapshot.market,
            "asset_type": "COMMON_STOCK",
            "trading_date": snapshot.trading_date.isoformat(),
            "provider_code": snapshot.market,
            "source_id": snapshot.source_id,
            "source_dataset": "daily_bars",
            "source_event_id": (
                f"{snapshot.market}:daily_bars:{snapshot.trading_date.isoformat()}"
            ),
            "source_version": "official-openapi-normalized-snapshot.v1",
            "source_revision_hash": source_revision_hash,
            # The original full response bytes were not retained by the first-stage
            # importer. Bind this research-only publication to the exact normalized
            # rows instead of pretending a raw payload digest is available.
            "source_payload_hash": snapshot.normalized_content_sha256,
            "source_url": snapshot.source_url,
            "source_metadata": {
                "source_versions": list(snapshot.source_versions),
                "source_payload_hash_basis": "NORMALIZED_ROW_COLLECTION",
            },
            "published_at": None,
            "first_observed_at": snapshot.first_observed_at.isoformat(),
            "available_at": snapshot.first_observed_at.isoformat(),
            "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
            "verification_status": "UNRESOLVED",
            "usage_scope": "BAR_PUBLICATION_RESEARCH_ONLY",
            "system_status": "RESEARCH_ONLY",
            "reason_codes": [
                "OFFICIAL_PUBLICATION_TIMESTAMP_UNVERIFIED",
                "SOURCE_PAYLOAD_HASH_DERIVED_FROM_NORMALIZED_ROWS",
                "BAR_PUBLICATION_RESEARCH_ONLY",
            ],
            "git_commit": _git_commit(),
            "library_versions": _library_versions(),
        }
        saved = self.repository.save_and_read(manifest)
        return DailyBarPublicationResult(
            market=snapshot.market,
            trading_date=snapshot.trading_date,
            publication_snapshot_id=_positive_integer(
                saved.get("publication_snapshot_id"), "publication_snapshot_id"
            ),
            snapshot_key=snapshot_key,
            object_key=artifact.object_key,
            created=created,
            parquet_sha256=artifact.parquet_sha256,
            normalized_content_sha256=snapshot.normalized_content_sha256,
            row_count=artifact.row_count,
        )


__all__ = [
    "DAILY_BAR_PUBLICATION_SCHEMA_VERSION",
    "DailyBarPublicationArtifact",
    "DailyBarPublicationManifestRepository",
    "DailyBarPublicationResult",
    "DailyBarPublicationService",
    "DailyBarPublicationSourceRepository",
    "DailyBarPublicationSourceRow",
    "DailyBarPublicationSourceSnapshot",
    "serialize_daily_bar_publication",
]
