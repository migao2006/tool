"""Read and verify one market-wide current daily-bar publication from R2."""

from __future__ import annotations

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import re
from typing import Any, Protocol, cast, final

from src.data.ingestion.contracts import IngestionError
from src.data.ingestion.daily_bar_publication import (
    DAILY_BAR_PUBLICATION_CONTENT_TYPE,
    DAILY_BAR_PUBLICATION_SCHEMA_VERSION,
    DailyBarPublicationSourceRow,
)
from src.data.object_storage.r2_client import R2Client


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MARKETS = frozenset({"TWSE", "TPEX"})


class DailyBarPublicationReaderWriter(Protocol):
    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
        offset: int = 0,
    ) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class DailyBarPublicationManifest:
    publication_snapshot_id: int
    snapshot_key: str
    bucket_name: str
    object_key: str
    object_etag: str | None
    schema_version: str
    parquet_sha256: str
    normalized_content_sha256: str
    byte_size: int
    row_count: int
    market: str
    trading_date: date
    source_id: int
    source_version: str
    source_revision_hash: str
    source_payload_hash: str
    first_observed_at: datetime
    available_at: datetime
    available_at_basis: str
    verification_status: str
    usage_scope: str
    system_status: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            self.publication_snapshot_id <= 0
            or self.market not in _MARKETS
            or self.schema_version != DAILY_BAR_PUBLICATION_SCHEMA_VERSION
            or self.byte_size <= 0
            or self.row_count <= 0
            or self.source_id <= 0
            or not self.object_key
            or not self.bucket_name
            or self.available_at_basis != "FIRST_OBSERVED_AT_RETRIEVAL"
            or self.verification_status not in {"UNRESOLVED", "CONFLICT"}
            or self.usage_scope != "BAR_PUBLICATION_RESEARCH_ONLY"
            or self.system_status not in {"RESEARCH_ONLY", "FAIL"}
        ):
            raise ValueError("daily-bar publication manifest contract is invalid")
        for digest in (
            self.snapshot_key,
            self.parquet_sha256,
            self.normalized_content_sha256,
            self.source_revision_hash,
            self.source_payload_hash,
        ):
            if _SHA256.fullmatch(digest) is None:
                raise ValueError("daily-bar publication manifest hash is invalid")
        for value in (self.first_observed_at, self.available_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("daily-bar publication manifest timestamp is naive")
        if not self.reason_codes:
            raise ValueError("research-only daily-bar publication needs reason codes")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "DailyBarPublicationManifest":
        def integer(name: str) -> int:
            raw = value.get(name)
            if isinstance(raw, bool):
                raise ValueError(f"{name} is invalid")
            parsed = int(str(raw))
            if parsed <= 0:
                raise ValueError(f"{name} is invalid")
            return parsed

        def text(name: str) -> str:
            parsed = str(value.get(name) or "").strip()
            if not parsed:
                raise ValueError(f"{name} is missing")
            return parsed

        def timestamp(name: str) -> datetime:
            parsed = datetime.fromisoformat(text(name).replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError(f"{name} is timezone-naive")
            return parsed.astimezone(timezone.utc)

        reasons = value.get("reason_codes")
        if not isinstance(reasons, list) or any(
            not isinstance(reason, str) or not reason for reason in reasons
        ):
            raise ValueError("reason_codes must be a non-empty string array")
        return cls(
            publication_snapshot_id=integer("publication_snapshot_id"),
            snapshot_key=text("snapshot_key").lower(),
            bucket_name=text("bucket_name"),
            object_key=text("object_key"),
            object_etag=(
                str(value["object_etag"]).strip() if value.get("object_etag") is not None else None
            ),
            schema_version=text("schema_version"),
            parquet_sha256=text("parquet_sha256").lower(),
            normalized_content_sha256=text("normalized_content_sha256").lower(),
            byte_size=integer("byte_size"),
            row_count=integer("row_count"),
            market=text("market").upper(),
            trading_date=date.fromisoformat(text("trading_date")),
            source_id=integer("source_id"),
            source_version=text("source_version"),
            source_revision_hash=text("source_revision_hash").lower(),
            source_payload_hash=text("source_payload_hash").lower(),
            first_observed_at=timestamp("first_observed_at"),
            available_at=timestamp("available_at"),
            available_at_basis=text("available_at_basis"),
            verification_status=text("verification_status"),
            usage_scope=text("usage_scope"),
            system_status=text("system_status"),
            reason_codes=tuple(cast(list[str], reasons)),
        )

    @property
    def snapshot_sha256(self) -> str:
        payload = {
            "publication_snapshot_id": self.publication_snapshot_id,
            "snapshot_key": self.snapshot_key,
            "bucket_name": self.bucket_name,
            "object_key": self.object_key,
            "schema_version": self.schema_version,
            "parquet_sha256": self.parquet_sha256,
            "normalized_content_sha256": self.normalized_content_sha256,
            "row_count": self.row_count,
            "market": self.market,
            "trading_date": self.trading_date.isoformat(),
            "source_id": self.source_id,
            "source_revision_hash": self.source_revision_hash,
            "available_at": self.available_at.isoformat(),
            "verification_status": self.verification_status,
            "usage_scope": self.usage_scope,
            "system_status": self.system_status,
            "reason_codes": self.reason_codes,
        }
        return sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class DailyBarPublicationSnapshot:
    manifest: DailyBarPublicationManifest
    rows: tuple[DailyBarPublicationSourceRow, ...]

    def __post_init__(self) -> None:
        if len(self.rows) != self.manifest.row_count:
            raise ValueError("daily-bar publication row count does not match manifest")
        if any(
            row.market != self.manifest.market
            or row.trade_date != self.manifest.trading_date
            or row.source_id != self.manifest.source_id
            for row in self.rows
        ):
            raise ValueError("daily-bar publication rows conflict with manifest")

    @property
    def by_symbol(self) -> dict[str, DailyBarPublicationSourceRow]:
        return {row.symbol: row for row in self.rows}


@final
class DailyBarPublicationSnapshotRepository:
    def __init__(self, writer: DailyBarPublicationReaderWriter) -> None:
        self.writer = writer

    def fetch_exact(
        self,
        *,
        market: str,
        trading_date: date,
    ) -> DailyBarPublicationManifest:
        normalized_market = market.strip().upper()
        if normalized_market not in _MARKETS:
            raise ValueError("market must be TWSE or TPEX")
        rows = self.writer.select_rows(
            "daily_bar_publication_snapshots",
            select=(
                "publication_snapshot_id,snapshot_key,bucket_name,object_key,"
                "object_etag,schema_version,parquet_sha256,normalized_content_sha256,"
                "byte_size,row_count,market,trading_date,source_id,source_version,"
                "source_revision_hash,source_payload_hash,first_observed_at,available_at,"
                "available_at_basis,verification_status,usage_scope,system_status,"
                "reason_codes"
            ),
            filters={
                "market": f"eq.{normalized_market}",
                "asset_type": "eq.COMMON_STOCK",
                "trading_date": f"eq.{trading_date.isoformat()}",
                "order": "available_at.desc,publication_snapshot_id.desc",
            },
            limit=2,
        )
        if not rows:
            raise IngestionError(
                "DAILY_BAR_PUBLICATION_SNAPSHOT_MISSING",
                "No current daily-bar publication exists for the required date",
            )
        try:
            return DailyBarPublicationManifest.from_mapping(rows[0])
        except (TypeError, ValueError) as error:
            raise IngestionError(
                "DAILY_BAR_PUBLICATION_MANIFEST_INVALID",
                "The current daily-bar publication manifest is invalid",
            ) from error


def _canonical_hash(rows: tuple[DailyBarPublicationSourceRow, ...]) -> str:
    return sha256(
        json.dumps(
            [row.canonical_mapping() for row in rows],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _pyarrow_modules() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ModuleNotFoundError as error:
        raise IngestionError(
            "PARQUET_DEPENDENCY_MISSING",
            "pyarrow is required to read current daily-bar publications",
        ) from error
    return pa, pq


@final
class DailyBarPublicationSnapshotReader:
    def __init__(self, store: R2Client) -> None:
        self.store = store

    def read(
        self,
        manifest: DailyBarPublicationManifest,
    ) -> DailyBarPublicationSnapshot:
        if manifest.bucket_name != self.store.bucket_name:
            raise IngestionError(
                "DAILY_BAR_PUBLICATION_BUCKET_MISMATCH",
                "The daily-bar publication manifest points to another bucket",
            )
        head = self.store.head(manifest.object_key)
        if (
            head is None
            or head.content_length != manifest.byte_size
            or head.content_type != DAILY_BAR_PUBLICATION_CONTENT_TYPE
            or head.metadata.get("parquet-sha256") != manifest.parquet_sha256
            or head.metadata.get("normalized-content-sha256") != manifest.normalized_content_sha256
        ):
            raise IngestionError(
                "DAILY_BAR_PUBLICATION_METADATA_INVALID",
                "The R2 daily-bar publication metadata does not match its manifest",
            )
        payload = self.store.get(manifest.object_key)
        if sha256(payload).hexdigest() != manifest.parquet_sha256:
            raise IngestionError(
                "DAILY_BAR_PUBLICATION_INTEGRITY_MISMATCH",
                "The R2 daily-bar publication checksum does not match its manifest",
            )
        _, pq = _pyarrow_modules()
        try:
            table = pq.read_table(BytesIO(payload))
        except Exception as error:
            raise IngestionError(
                "DAILY_BAR_PUBLICATION_PARQUET_INVALID",
                "The R2 daily-bar publication cannot be read as Parquet",
            ) from error
        metadata = table.schema.metadata or {}
        expected_metadata = {
            b"publication.schema_version": manifest.schema_version.encode("ascii"),
            b"publication.market": manifest.market.encode("ascii"),
            b"publication.asset_type": b"COMMON_STOCK",
            b"publication.trading_date": manifest.trading_date.isoformat().encode("ascii"),
            b"publication.normalized_content_sha256": (
                manifest.normalized_content_sha256.encode("ascii")
            ),
            b"publication.row_count": str(manifest.row_count).encode("ascii"),
            b"publication.system_status": b"RESEARCH_ONLY",
        }
        if any(metadata.get(name) != value for name, value in expected_metadata.items()):
            raise IngestionError(
                "DAILY_BAR_PUBLICATION_PARQUET_METADATA_INVALID",
                "The daily-bar publication Parquet metadata is inconsistent",
            )
        parsed: list[DailyBarPublicationSourceRow] = []
        try:
            for raw in cast(list[dict[str, object]], table.to_pylist()):
                parsed.append(
                    DailyBarPublicationSourceRow(
                        daily_bar_id=int(str(raw["daily_bar_id"])),
                        security_id=int(str(raw["security_id"])),
                        symbol=str(raw["symbol"]),
                        market=str(raw["market"]),
                        trade_date=cast(date, raw["trade_date"]),
                        open_price=cast(float | None, raw.get("open_price")),
                        high_price=cast(float | None, raw.get("high_price")),
                        low_price=cast(float | None, raw.get("low_price")),
                        close_price=cast(float | None, raw.get("close_price")),
                        trading_volume=cast(float | None, raw.get("trading_volume")),
                        trading_value=cast(float | None, raw.get("trading_value")),
                        trade_count=cast(int | None, raw.get("trade_count")),
                        source_id=int(str(raw["source_id"])),
                        source_version=str(raw["source_version"]),
                        available_at=cast(datetime, raw["available_at"]),
                    )
                )
        except (KeyError, TypeError, ValueError) as error:
            raise IngestionError(
                "DAILY_BAR_PUBLICATION_ROW_INVALID",
                "The daily-bar publication contains an invalid row",
            ) from error
        rows = tuple(sorted(parsed, key=lambda row: row.symbol))
        if (
            len(rows) != manifest.row_count
            or len({row.security_id for row in rows}) != len(rows)
            or _canonical_hash(rows) != manifest.normalized_content_sha256
        ):
            raise IngestionError(
                "DAILY_BAR_PUBLICATION_CONTENT_MISMATCH",
                "The daily-bar publication rows do not reproduce the manifest",
            )
        return DailyBarPublicationSnapshot(manifest=manifest, rows=rows)


__all__ = [
    "DailyBarPublicationManifest",
    "DailyBarPublicationSnapshot",
    "DailyBarPublicationSnapshotReader",
    "DailyBarPublicationSnapshotRepository",
]
