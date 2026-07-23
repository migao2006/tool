from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import pyarrow.parquet as pq
import pandas as pd
import pytest

from src.data.archive.historical_parquet_reader import HistoricalParquetReader
from src.data.archive.manifest_repository import HistoricalArchiveManifestSnapshot
from src.data.ingestion.daily_bar_publication import DailyBarPublicationSourceRow
from src.data.ingestion.historical_archive_contracts import HistoricalArchiveRequest
from src.data.ingestion.historical_parquet_serializer import (
    serialize_historical_parquet,
)
from src.data.object_storage.r2_client import R2Client, R2Settings
from src.data.research.archive_feature_rows import (
    ArchiveFeatureRowAdapter,
    ArchiveRowSource,
    SourceProvenance,
    canonical_record,
    output_row,
    publication_canonical_record,
)
from src.data.research.daily_bar_publication_snapshot import (
    DailyBarPublicationManifest,
    DailyBarPublicationSnapshot,
)
from src.data.research.twse_archive_feature_builder import (
    TwseArchiveFeatureBuildError,
    TwseArchiveFeatureDatasetBuilder,
)
from src.data.research.twse_archive_feature_contracts import (
    TWSE_ARCHIVE_FEATURE_DATASET_VERSION,
    TwseCurrentSecurityIdentity,
    TwseIdentitySnapshot,
    dataset_snapshot_hash,
    identity_snapshot_hash,
)
from src.data.research.twse_archive_feature_parquet import (
    TwseArchiveFeatureParquetWriter,
)
from src.features.price_volume_builder import build_price_volume_features
from src.features.price_volume_schema import PRICE_VOLUME_FEATURE_NAMES
from src.pipeline.twse_research_assembly_inputs import feature_records, reason_codes


OBSERVED_AT = datetime(2026, 7, 19, 4, tzinfo=timezone.utc)
START_DATE = date(2021, 1, 1)
END_DATE = START_DATE + timedelta(days=71)
SOURCE_PAYLOAD_HASH = "c" * 64
BUCKET = "alpha-lens-archive"
CANONICAL_ROW_COLUMNS = (
    "security_id",
    "listing_period_id",
    "market",
    "symbol",
    "asset_type",
    "trade_date",
    "decision_at",
    "available_at",
    "available_at_basis",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "trading_volume",
    "trading_value",
    "point_in_time_status",
    "parse_status",
    "reason_codes",
)
OUTPUT_ROW_COLUMNS = (
    "dataset_snapshot_sha256",
    "source_archive_snapshot_sha256",
    "current_identity_snapshot_sha256",
    "archive_id",
    "source_object_key",
    "source_payload_sha256",
    "source_parquet_sha256",
    "security_id",
    "listing_period_id",
    "symbol",
    "market",
    "asset_type",
    "listing_date",
    "decision_date",
    "decision_at",
    "horizon",
    "decision_time_policy_version",
    "feature_schema_version",
    "feature_schema_hash",
    "price_basis",
    "availability_mode",
    "decision_close_price",
    "latest_available_at",
    "latest_observed_available_at",
    "point_in_time_audit_pass",
    "hard_fail",
    "research_limitation_reason_codes",
    "hard_fail_reason_codes",
    "label_status",
    "usage_scope",
    "system_status",
    "reason_codes",
    "source_reason_codes",
    *PRICE_VOLUME_FEATURE_NAMES,
)


class MemoryS3Client:
    def __init__(self, body: bytes, metadata: dict[str, str]) -> None:
        self.body = body
        self.metadata = metadata

    def head_object(self, **kwargs: Any) -> dict[str, object]:
        return {
            "ContentLength": len(self.body),
            "ContentType": "application/vnd.apache.parquet",
            "Metadata": self.metadata,
            "ETag": '"archive-etag"',
        }

    def get_object(self, **kwargs: Any) -> dict[str, object]:
        return {"Body": BytesIO(self.body)}

    def put_object(self, **kwargs: Any) -> dict[str, object]:
        raise AssertionError("dataset builder must not write R2")

    def delete_object(self, **kwargs: Any) -> dict[str, object]:
        raise AssertionError("dataset builder must not delete R2")


def _row(index: int) -> dict[str, object]:
    trade_date = START_DATE + timedelta(days=index)
    close = 100 + index
    reasons = [
        "SOURCE_MARKET_UNAVAILABLE",
        "IDENTITY_UNRESOLVED",
        "POINT_IN_TIME_UNVERIFIED",
        "AVAILABLE_AT_FIRST_RETRIEVAL_ONLY",
        "RAW_LANDING_ONLY",
    ]
    return {
        "landing_key": f"{index + 1:064x}",
        "source_code": "FINMIND",
        "source_dataset": "daily_bars",
        "source_symbol": "2330",
        "source_market_claim": None,
        "source_market_basis": "UNAVAILABLE",
        "source_version": "api.v4",
        "source_revision_hash": f"{index + 1000:064x}",
        "source_payload_hash": SOURCE_PAYLOAD_HASH,
        "source_url": "https://api.finmindtrade.com/api/v4/data",
        "source_row_index": index,
        "source_row": {"stock_id": "2330", "date": trade_date.isoformat()},
        "first_observed_at": OBSERVED_AT.isoformat(),
        "available_at": OBSERVED_AT.isoformat(),
        "available_at_basis": "FIRST_OBSERVED_AT_RETRIEVAL",
        "identity_resolution_status": "UNRESOLVED",
        "point_in_time_status": "UNVERIFIED",
        "usage_scope": "RAW_LANDING_ONLY",
        "system_status": "RESEARCH_ONLY",
        "reason_codes": reasons,
        "source_trade_date": trade_date.isoformat(),
        "trade_date": trade_date.isoformat(),
        "parse_status": "PARSED",
        "open_price": str(close - 1),
        "high_price": str(close + 1),
        "low_price": str(close - 2),
        "close_price": str(close),
        "trading_volume": str(1_000_000 + index),
        "trading_value": str(close * (1_000_000 + index)),
        "trade_count": 1_000 + index,
    }


def _parsed_row(index: int) -> dict[str, object]:
    row = _row(index)
    row["trade_date"] = START_DATE + timedelta(days=index)
    row["available_at"] = OBSERVED_AT
    return row


def _archive(
    rows: list[dict[str, object]] | None = None,
) -> tuple[HistoricalParquetReader, HistoricalArchiveManifestSnapshot]:
    source_rows = rows if rows is not None else [_row(index) for index in range(72)]
    request = HistoricalArchiveRequest(
        scheduled_market="TWSE",
        asset_type="COMMON_STOCK",
        source_symbol="2330",
        requested_start_date=START_DATE,
        requested_end_date=END_DATE,
        source_payload_sha256=SOURCE_PAYLOAD_HASH,
        retrieved_at=OBSERVED_AT,
    )
    artifact = serialize_historical_parquet(
        source_rows,
        request=request,
    )
    store = MemoryS3Client(artifact.payload, dict(artifact.object_metadata()))
    reader = HistoricalParquetReader(
        R2Client(
            R2Settings(
                account_id="account123",
                access_key_id="access-key",
                secret_access_key="secret-key",
                bucket_name=BUCKET,
            ),
            s3_client=store,
        )
    )
    object_key = artifact.object_key
    manifest = {
        "archive_id": 1,
        "archive_key": sha256(f"{BUCKET}\0{object_key}".encode()).hexdigest(),
        "storage_provider": "CLOUDFLARE_R2",
        "bucket_name": BUCKET,
        "object_key": object_key,
        "object_etag": '"archive-etag"',
        "schema_version": artifact.schema_version,
        "provider_code": "FINMIND",
        "source_dataset": "daily_bars",
        "source_version": "api.v4",
        "source_symbol": "2330",
        "scheduled_market": "TWSE",
        "asset_type": "COMMON_STOCK",
        "requested_start_date": START_DATE.isoformat(),
        "requested_end_date": END_DATE.isoformat(),
        "min_trade_date": START_DATE.isoformat(),
        "max_trade_date": END_DATE.isoformat(),
        "source_payload_hash": SOURCE_PAYLOAD_HASH,
        "parquet_sha256": artifact.content_sha256,
        "byte_size": artifact.byte_size,
        "row_count": 72,
        "parsed_row_count": 72,
        "quarantined_row_count": 0,
        "first_observed_at": OBSERVED_AT.isoformat(),
        "point_in_time_status": "UNVERIFIED",
        "usage_scope": "RAW_LANDING_ONLY",
        "system_status": "RESEARCH_ONLY",
        "reason_codes": ["POINT_IN_TIME_UNVERIFIED", "RAW_LANDING_ONLY"],
    }
    snapshot = HistoricalArchiveManifestSnapshot(
        rows=(MappingProxyType(manifest),),
        snapshot_sha256="a" * 64,
        complete=True,
    )
    return reader, snapshot


def _publication_snapshot(
    trading_date: date,
    *,
    available_at: datetime = OBSERVED_AT,
    market: str = "TWSE",
    security_id: int = 2330,
    symbol: str = "2330",
) -> DailyBarPublicationSnapshot:
    current_row = DailyBarPublicationSourceRow(
        daily_bar_id=9001,
        security_id=security_id,
        symbol=symbol,
        market=market,
        trade_date=trading_date,
        open_price=171.0,
        high_price=173.0,
        low_price=170.0,
        close_price=172.0,
        trading_volume=1_200_000.0,
        trading_value=206_400_000.0,
        trade_count=1_200,
        source_id=7,
        source_version="official-openapi.v1",
        available_at=available_at,
    )
    publication_manifest = DailyBarPublicationManifest(
        publication_snapshot_id=91,
        snapshot_key="1" * 64,
        bucket_name=BUCKET,
        object_key=f"current/v1/{market.lower()}.parquet",
        object_etag='"publication"',
        schema_version="daily-bar-publication.v1",
        parquet_sha256="2" * 64,
        normalized_content_sha256="3" * 64,
        byte_size=100,
        row_count=1,
        market=market,
        trading_date=trading_date,
        source_id=7,
        source_version="official-openapi-normalized-snapshot.v1",
        source_revision_hash="4" * 64,
        source_payload_hash="5" * 64,
        first_observed_at=available_at,
        available_at=available_at,
        available_at_basis="FIRST_OBSERVED_AT_RETRIEVAL",
        verification_status="UNRESOLVED",
        usage_scope="BAR_PUBLICATION_RESEARCH_ONLY",
        system_status="RESEARCH_ONLY",
        reason_codes=(
            "OFFICIAL_PUBLICATION_TIMESTAMP_UNVERIFIED",
            "BAR_PUBLICATION_RESEARCH_ONLY",
        ),
    )
    return DailyBarPublicationSnapshot(
        manifest=publication_manifest,
        rows=(current_row,),
    )


def test_public_row_adapters_preserve_canonical_output_and_compatibility_contracts() -> None:
    from src.data.research import twse_archive_feature_rows as compatibility_rows

    identity = TwseCurrentSecurityIdentity(
        security_id=2330,
        symbol="2330",
        listing_date=START_DATE,
    )
    archive_record = canonical_record(
        _parsed_row(0),
        identity=identity,
        market="TWSE",
    )
    publication = _publication_snapshot(START_DATE)
    publication_record = publication_canonical_record(
        publication.rows[0],
        identity=identity,
    )

    assert tuple(archive_record) == CANONICAL_ROW_COLUMNS
    assert tuple(publication_record) == CANONICAL_ROW_COLUMNS
    assert archive_record["market"] == publication_record["market"] == "TWSE"
    assert archive_record["asset_type"] == publication_record["asset_type"] == "COMMON_STOCK"
    assert archive_record["point_in_time_status"] == "UNVERIFIED"
    assert publication_record["point_in_time_status"] == "UNVERIFIED"
    assert archive_record["reason_codes"] == publication_record["reason_codes"]
    assert archive_record["available_at_basis"] == "FIRST_OBSERVED_AT_RETRIEVAL"
    assert publication_record["available_at_basis"] == "FIRST_OBSERVED_AT_RETRIEVAL"

    canonical_rows = [
        canonical_record(
            _parsed_row(index),
            identity=identity,
            market="TWSE",
        )
        for index in range(72)
    ]
    features = build_price_volume_features(
        canonical_rows,
        market="TWSE",
        availability_mode="RESEARCH_SCHEDULING_HINT",
    )
    feature = features.rows[-1]
    assert feature.hard_fail is False
    adapted = output_row(
        feature,
        identity=identity,
        provenance=SourceProvenance(
            archive_id=1,
            object_key="historical/twse/2330.parquet",
            source_payload_sha256=SOURCE_PAYLOAD_HASH,
            parquet_sha256="d" * 64,
            source_reason_codes=("POINT_IN_TIME_UNVERIFIED", "RAW_LANDING_ONLY"),
        ),
        dataset_snapshot_sha256="e" * 64,
        source_archive_snapshot_sha256="a" * 64,
        current_identity_snapshot_sha256="b" * 64,
        market="TWSE",
    )

    assert tuple(adapted) == OUTPUT_ROW_COLUMNS
    assert adapted["horizon"] == 5
    assert adapted["hard_fail"] is False
    assert adapted["usage_scope"] == "FEATURE_RESEARCH_ONLY"
    assert adapted["system_status"] == "RESEARCH_ONLY"
    assert adapted["point_in_time_audit_pass"] is False
    assert json.loads(str(adapted["source_reason_codes"])) == [
        "POINT_IN_TIME_UNVERIFIED",
        "RAW_LANDING_ONLY",
    ]
    assert compatibility_rows.SourceProvenance is SourceProvenance
    assert compatibility_rows.canonical_record is canonical_record
    assert compatibility_rows.output_row is output_row


def test_extracted_row_adapter_selects_sources_and_provenance_deterministically() -> None:
    adapter = ArchiveFeatureRowAdapter(market="TWSE")
    identity = TwseCurrentSecurityIdentity(
        security_id=2330,
        symbol="2330",
        listing_date=START_DATE,
    )
    archive_rows = [_parsed_row(index) for index in range(3)]
    archive_rows[-1]["parse_status"] = "QUARANTINED"
    for row in archive_rows:
        row["reason_codes"] = json.dumps(
            row["reason_codes"],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    source = ArchiveRowSource(
        archive_id=7,
        object_key="historical/twse/2330.parquet",
        source_payload_sha256=SOURCE_PAYLOAD_HASH,
        parquet_sha256="d" * 64,
        manifest_reason_codes=("POINT_IN_TIME_UNVERIFIED", "RAW_LANDING_ONLY"),
        rows=tuple(archive_rows),
        row_count=3,
    )
    publication = _publication_snapshot(START_DATE + timedelta(days=1))

    adapted = adapter.adapt_source_rows(
        archive_sources=(source,),
        identity=identity,
        publication_row=publication.rows[0],
        publication_manifest=publication.manifest,
    )

    assert [row["trade_date"] for row in adapted.records] == [
        START_DATE,
        START_DATE + timedelta(days=1),
    ]
    assert adapted.source_row_count == 4
    assert adapted.parsed_source_row_count == 3
    assert adapted.exclusion_reason_counts == {
        "ARCHIVE_ROW_QUARANTINED": 1,
        "DAILY_PUBLICATION_OVERLAPS_ARCHIVE": 1,
    }
    assert tuple(adapted.provenance_by_date) == (
        START_DATE,
        START_DATE + timedelta(days=1),
    )
    assert adapted.provenance_by_date[START_DATE].archive_id == 7
    assert adapted.provenance_by_date[START_DATE + timedelta(days=1)].archive_id == 7
    assert adapted.provenance_by_date[START_DATE].source_reason_codes[:2] == (
        "POINT_IN_TIME_UNVERIFIED",
        "RAW_LANDING_ONLY",
    )
    assert adapted.records[0] == adapter.canonical_record(
        archive_rows[0],
        identity=identity,
    )
    assert adapted.records[0] == canonical_record(
        archive_rows[0],
        identity=identity,
        market="TWSE",
    )
    assert adapter.publication_canonical_record(
        publication.rows[0],
        identity=identity,
    ) == publication_canonical_record(
        publication.rows[0],
        identity=identity,
    )
    assert all(row["point_in_time_status"] == "UNVERIFIED" for row in adapted.records)

    with pytest.raises(TwseArchiveFeatureBuildError) as captured:
        _ = ArchiveFeatureRowAdapter(market="TPEX").canonical_record(
            archive_rows[0],
            identity=identity,
        )
    assert captured.value.reason_code == "TPEX_CURRENT_IDENTITY_SCOPE_MISMATCH"


def test_extracted_row_adapter_fails_closed_on_duplicate_dates_within_one_source() -> None:
    adapter = ArchiveFeatureRowAdapter(market="TWSE")
    identity = TwseCurrentSecurityIdentity(
        security_id=2330,
        symbol="2330",
        listing_date=START_DATE,
    )
    archive_rows = [_parsed_row(index) for index in range(72)]
    duplicate = dict(archive_rows[-1])
    duplicate["close_price"] = "999"
    archive_rows.append(duplicate)
    for row in archive_rows:
        row["reason_codes"] = json.dumps(
            row["reason_codes"],
            ensure_ascii=False,
            separators=(",", ":"),
        )

    adapted_sources = adapter.adapt_source_rows(
        archive_sources=(
            ArchiveRowSource(
                archive_id=21,
                object_key="historical/twse/2330-single-source.parquet",
                source_payload_sha256=SOURCE_PAYLOAD_HASH,
                parquet_sha256="6" * 64,
                manifest_reason_codes=(
                    "POINT_IN_TIME_UNVERIFIED",
                    "RAW_LANDING_ONLY",
                ),
                rows=tuple(archive_rows),
                row_count=73,
            ),
        ),
        identity=identity,
    )
    features = build_price_volume_features(
        adapted_sources.records,
        market="TWSE",
        availability_mode="RESEARCH_SCHEDULING_HINT",
    )
    duplicate_date = END_DATE
    duplicate_feature = next(
        feature for feature in features.rows if feature.decision_date == duplicate_date
    )

    assert adapted_sources.source_row_count == 73
    assert adapted_sources.parsed_source_row_count == 73
    assert len(adapted_sources.records) == 73
    assert len(adapted_sources.provenance_by_date) == 72
    assert duplicate_feature.decision_close_price == 171.0
    assert duplicate_feature.hard_fail is True
    assert duplicate_feature.hard_fail_reason_codes == ("DUPLICATE_CANONICAL_BAR",)

    adapted_output = adapter.adapt_output_rows(
        features.rows,
        identity=identity,
        provenance_by_date=adapted_sources.provenance_by_date,
        dataset_snapshot_sha256="e" * 64,
        source_archive_snapshot_sha256="a" * 64,
        current_identity_snapshot_sha256="b" * 64,
    )

    decision_dates = [cast(date, row["decision_date"]) for row in adapted_output.rows]
    assert duplicate_date not in decision_dates
    assert decision_dates == sorted(set(decision_dates))
    assert adapted_output.exclusion_reason_counts["DUPLICATE_CANONICAL_BAR"] == 1
    assert {row["archive_id"] for row in adapted_output.rows} == {21}


def test_extracted_row_adapter_accumulates_incremental_sources_exactly_once() -> None:
    adapter = ArchiveFeatureRowAdapter(market="TWSE")
    identity = TwseCurrentSecurityIdentity(
        security_id=2330,
        symbol="2330",
        listing_date=START_DATE,
    )
    first_rows = [_parsed_row(index) for index in range(66)]
    quarantined = dict(first_rows[0])
    quarantined["parse_status"] = "QUARANTINED"
    first_rows.append(quarantined)
    second_rows = [_parsed_row(0), *[_parsed_row(index) for index in range(66, 72)]]
    for row in (*first_rows, *second_rows):
        row["reason_codes"] = json.dumps(
            row["reason_codes"],
            ensure_ascii=False,
            separators=(",", ":"),
        )

    first = adapter.adapt_source_rows(
        archive_sources=(
            ArchiveRowSource(
                archive_id=31,
                object_key="historical/twse/2330-first.parquet",
                source_payload_sha256="7" * 64,
                parquet_sha256="8" * 64,
                manifest_reason_codes=("FIRST_ARCHIVE",),
                rows=tuple(first_rows),
                row_count=67,
            ),
        ),
        identity=identity,
    )
    second = adapter.adapt_source_rows(
        archive_sources=(
            ArchiveRowSource(
                archive_id=32,
                object_key="historical/twse/2330-second.parquet",
                source_payload_sha256="9" * 64,
                parquet_sha256="a" * 64,
                manifest_reason_codes=("SECOND_ARCHIVE",),
                rows=tuple(second_rows),
                row_count=7,
            ),
        ),
        identity=identity,
        previous=first,
    )
    publication = _publication_snapshot(END_DATE)
    final = adapter.adapt_source_rows(
        archive_sources=(),
        identity=identity,
        publication_row=publication.rows[0],
        publication_manifest=publication.manifest,
        previous=second,
    )
    duplicate_date = START_DATE
    second_source_output_start = START_DATE + timedelta(days=66)

    assert first.source_row_count == 67
    assert first.parsed_source_row_count == 66
    assert first.exclusion_reason_counts == {"ARCHIVE_ROW_QUARANTINED": 1}
    assert len(first.records) == 66
    assert first.provenance_by_date[duplicate_date].archive_id == 31

    assert second.source_row_count == 74
    assert second.parsed_source_row_count == 73
    assert second.exclusion_reason_counts == {"ARCHIVE_ROW_QUARANTINED": 1}
    assert len(second.records) == 73
    assert len(second.provenance_by_date) == 72
    assert second.provenance_by_date[duplicate_date].archive_id == 32

    assert final.source_row_count == 75
    assert final.parsed_source_row_count == 74
    assert final.exclusion_reason_counts == {
        "ARCHIVE_ROW_QUARANTINED": 1,
        "DAILY_PUBLICATION_OVERLAPS_ARCHIVE": 1,
    }
    assert final.records == second.records
    assert final.provenance_by_date == second.provenance_by_date
    assert final.provenance_by_date[END_DATE].archive_id == 32

    features = build_price_volume_features(
        final.records,
        market="TWSE",
        availability_mode="RESEARCH_SCHEDULING_HINT",
    )
    adapted_output = adapter.adapt_output_rows(
        features.rows,
        identity=identity,
        provenance_by_date=final.provenance_by_date,
        dataset_snapshot_sha256="e" * 64,
        source_archive_snapshot_sha256="a" * 64,
        current_identity_snapshot_sha256="b" * 64,
    )

    decision_dates = [cast(date, row["decision_date"]) for row in adapted_output.rows]
    assert duplicate_date not in decision_dates
    assert decision_dates == sorted(set(decision_dates))
    assert adapted_output.exclusion_reason_counts["DUPLICATE_CANONICAL_BAR"] == 10
    for row in adapted_output.rows:
        decision_date = cast(date, row["decision_date"])
        expected_archive_id = 31 if decision_date < second_source_output_start else 32
        assert row["archive_id"] == expected_archive_id


def test_extracted_row_adapter_excludes_hard_fail_and_adapts_output_rows() -> None:
    adapter = ArchiveFeatureRowAdapter(market="TWSE")
    identity = TwseCurrentSecurityIdentity(
        security_id=2330,
        symbol="2330",
        listing_date=START_DATE,
    )
    archive_rows = [_parsed_row(index) for index in range(72)]
    archive_rows[-1]["high_price"] = "0"
    for row in archive_rows:
        row["reason_codes"] = json.dumps(
            row["reason_codes"],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    adapted_sources = adapter.adapt_source_rows(
        archive_sources=(
            ArchiveRowSource(
                archive_id=11,
                object_key="historical/twse/2330.parquet",
                source_payload_sha256=SOURCE_PAYLOAD_HASH,
                parquet_sha256="d" * 64,
                manifest_reason_codes=(
                    "POINT_IN_TIME_UNVERIFIED",
                    "RAW_LANDING_ONLY",
                ),
                rows=tuple(archive_rows),
                row_count=72,
            ),
        ),
        identity=identity,
    )
    features = build_price_volume_features(
        adapted_sources.records,
        market="TWSE",
        availability_mode="RESEARCH_SCHEDULING_HINT",
    )

    adapted_output = adapter.adapt_output_rows(
        features.rows,
        identity=identity,
        provenance_by_date=adapted_sources.provenance_by_date,
        dataset_snapshot_sha256="e" * 64,
        source_archive_snapshot_sha256="a" * 64,
        current_identity_snapshot_sha256="b" * 64,
    )

    assert len(adapted_output.rows) == 11
    expected_exclusions = Counter(
        reason
        for feature in features.rows
        if feature.hard_fail
        for reason in feature.hard_fail_reason_codes
    )
    assert adapted_output.exclusion_reason_counts == dict(
        sorted(expected_exclusions.items())
    )
    assert adapted_output.exclusion_reason_counts["FEATURE_INPUT_INVALID:high_price"] == 1
    decision_dates: list[date] = []
    for row in adapted_output.rows:
        decision_date = row["decision_date"]
        latest_available_at = row["latest_available_at"]
        decision_at = row["decision_at"]
        assert type(decision_date) is date
        assert isinstance(latest_available_at, datetime)
        assert isinstance(decision_at, datetime)
        assert latest_available_at <= decision_at
        decision_dates.append(decision_date)
    assert decision_dates == sorted(decision_dates)
    assert all(row["archive_id"] == 11 for row in adapted_output.rows)
    assert all(row["horizon"] == 5 for row in adapted_output.rows)
    assert all(row["hard_fail"] is False for row in adapted_output.rows)
    assert all(row["usage_scope"] == "FEATURE_RESEARCH_ONLY" for row in adapted_output.rows)
    assert all(row["system_status"] == "RESEARCH_ONLY" for row in adapted_output.rows)
    assert all(
        row["latest_observed_available_at"] == OBSERVED_AT
        for row in adapted_output.rows
    )
    first_feature = next(feature for feature in features.rows if not feature.hard_fail)
    assert adapted_output.rows[0] == output_row(
        first_feature,
        identity=identity,
        provenance=adapted_sources.provenance_by_date[first_feature.decision_date],
        dataset_snapshot_sha256="e" * 64,
        source_archive_snapshot_sha256="a" * 64,
        current_identity_snapshot_sha256="b" * 64,
        market="TWSE",
    )


def test_builder_preserves_writer_success_and_abort_call_order() -> None:
    class RecordingWriter:
        def __init__(self, *, fail_write: bool = False) -> None:
            self.fail_write = fail_write
            self.events: list[tuple[str, int | None]] = []

        def write_rows(self, rows: tuple[dict[str, object], ...]) -> None:
            self.events.append(("write_rows", len(rows)))
            if self.fail_write:
                raise RuntimeError("recording writer failed")

        def finish(self) -> None:
            self.events.append(("finish", None))

        def abort(self) -> None:
            self.events.append(("abort", None))

    reader, manifests = _archive()
    identity = TwseCurrentSecurityIdentity(
        security_id=2330,
        symbol="2330",
        listing_date=START_DATE,
    )
    identities = TwseIdentitySnapshot(
        by_symbol={"2330": identity},
        snapshot_sha256=identity_snapshot_hash({"2330": identity}),
    )
    successful_writer = RecordingWriter()

    audit = TwseArchiveFeatureDatasetBuilder(reader).build(
        manifests=manifests,
        identities=identities,
        writer=cast(Any, successful_writer),
    )

    assert audit.output_row_count == 12
    assert successful_writer.events == [("write_rows", 12), ("finish", None)]

    failing_writer = RecordingWriter(fail_write=True)
    with pytest.raises(RuntimeError, match="recording writer failed"):
        _ = TwseArchiveFeatureDatasetBuilder(reader).build(
            manifests=manifests,
            identities=identities,
            writer=cast(Any, failing_writer),
        )

    assert failing_writer.events == [("write_rows", 12), ("abort", None)]


def test_builder_streams_eligible_rows_and_preserves_research_limits(
    tmp_path: Path,
) -> None:
    reader, manifests = _archive()
    identity = TwseCurrentSecurityIdentity(
        security_id=2330,
        symbol="2330",
        listing_date=START_DATE + timedelta(days=2),
    )
    identities = TwseIdentitySnapshot(
        by_symbol={"2330": identity},
        snapshot_sha256=identity_snapshot_hash({"2330": identity}),
    )
    output = tmp_path / "twse-features.parquet"
    dataset_hash = dataset_snapshot_hash(
        source_archive_snapshot_sha256=manifests.snapshot_sha256,
        current_identity_snapshot_sha256=identities.snapshot_sha256,
    )
    writer = TwseArchiveFeatureParquetWriter(
        output,
        dataset_snapshot_sha256=dataset_hash,
        source_archive_snapshot_sha256=manifests.snapshot_sha256,
        current_identity_snapshot_sha256=identities.snapshot_sha256,
    )

    audit = TwseArchiveFeatureDatasetBuilder(
        reader,
        now_fn=lambda: OBSERVED_AT,
    ).build(manifests=manifests, identities=identities, writer=writer)

    parquet = pq.ParquetFile(output)
    table = parquet.read()
    assert audit.system_status == "RESEARCH_ONLY"
    assert audit.label_status == "LABELS_NOT_ASSEMBLED"
    assert audit.verified_archive_count == 1
    assert audit.source_row_count == 72
    assert audit.output_row_count == 10
    assert audit.excluded_row_count == 62
    assert audit.exclusion_reason_counts["TRADE_DATE_BEFORE_CURRENT_LISTING_DATE"] == 2
    assert table.num_rows == 10
    assert table["decision_close_price"][-1].as_py() == 171.0
    assert "net_return" not in table.column_names
    assert "alpha" not in table.column_names
    assert set(table["label_status"].to_pylist()) == {"LABELS_NOT_ASSEMBLED"}
    assert set(table["availability_mode"].to_pylist()) == {"RESEARCH_SCHEDULING_HINT"}
    assert set(table["point_in_time_audit_pass"].to_pylist()) == {False}
    assert "RESEARCH_SCHEDULING_HINT" in table["research_limitation_reason_codes"][0].as_py()
    reasons = json.loads(table["reason_codes"][0].as_py())
    assert "LABELS_NOT_ASSEMBLED" in reasons
    assert "IDENTITY_UNRESOLVED" in reasons
    assert parquet.schema_arrow.metadata[b"system.status"] == b"RESEARCH_ONLY"
    assert parquet.schema_arrow.metadata[b"dataset.version"] == (
        TWSE_ARCHIVE_FEATURE_DATASET_VERSION.encode("ascii")
    )
    assert parquet.schema_arrow.metadata[b"labels.status"] == b"LABELS_NOT_ASSEMBLED"
    assert {
        parquet.metadata.row_group(group).column(column).compression
        for group in range(parquet.metadata.num_row_groups)
        for column in range(parquet.metadata.num_columns)
    } == {"ZSTD"}
    normalized = feature_records(pd.read_parquet(output))
    assert "RESEARCH_SCHEDULING_HINT" in reason_codes(
        normalized[0]["research_limitation_reason_codes"]
    )


def test_builder_rejects_empty_manifest_snapshot_without_publishing(
    tmp_path: Path,
) -> None:
    reader, _ = _archive()
    identity = TwseCurrentSecurityIdentity(
        security_id=2330,
        symbol="2330",
        listing_date=START_DATE,
    )
    identities = TwseIdentitySnapshot(
        by_symbol={"2330": identity},
        snapshot_sha256=identity_snapshot_hash({"2330": identity}),
    )
    manifests = HistoricalArchiveManifestSnapshot(
        rows=(),
        snapshot_sha256=sha256(b"").hexdigest(),
        complete=True,
    )
    output = tmp_path / "must-not-exist.parquet"
    writer = TwseArchiveFeatureParquetWriter(
        output,
        dataset_snapshot_sha256=dataset_snapshot_hash(
            source_archive_snapshot_sha256=manifests.snapshot_sha256,
            current_identity_snapshot_sha256=identities.snapshot_sha256,
        ),
        source_archive_snapshot_sha256=manifests.snapshot_sha256,
        current_identity_snapshot_sha256=identities.snapshot_sha256,
    )

    with pytest.raises(TwseArchiveFeatureBuildError) as captured:
        _ = TwseArchiveFeatureDatasetBuilder(reader).build(
            manifests=manifests,
            identities=identities,
            writer=writer,
        )

    assert captured.value.reason_code == "TWSE_ARCHIVE_MANIFESTS_EMPTY"
    assert not output.exists()
    assert not writer.partial_path.exists()


def test_builder_rejects_overlapping_symbol_archive_campaigns(
    tmp_path: Path,
) -> None:
    reader, original = _archive()
    duplicate = dict(original.rows[0])
    duplicate["archive_id"] = 2
    manifests = HistoricalArchiveManifestSnapshot(
        rows=(original.rows[0], MappingProxyType(duplicate)),
        snapshot_sha256="b" * 64,
        complete=True,
    )
    identity = TwseCurrentSecurityIdentity(
        security_id=2330,
        symbol="2330",
        listing_date=START_DATE,
    )
    identities = TwseIdentitySnapshot(
        by_symbol={"2330": identity},
        snapshot_sha256=identity_snapshot_hash({"2330": identity}),
    )
    output = tmp_path / "must-not-overlap.parquet"
    writer = TwseArchiveFeatureParquetWriter(
        output,
        dataset_snapshot_sha256=dataset_snapshot_hash(
            source_archive_snapshot_sha256=manifests.snapshot_sha256,
            current_identity_snapshot_sha256=identities.snapshot_sha256,
        ),
        source_archive_snapshot_sha256=manifests.snapshot_sha256,
        current_identity_snapshot_sha256=identities.snapshot_sha256,
    )

    with pytest.raises(TwseArchiveFeatureBuildError) as captured:
        _ = TwseArchiveFeatureDatasetBuilder(reader).build(
            manifests=manifests,
            identities=identities,
            writer=writer,
        )

    assert captured.value.reason_code == "TWSE_ARCHIVE_DATE_RANGE_OVERLAP"
    assert not output.exists()
    assert not writer.partial_path.exists()


def test_builder_merges_exact_date_current_publication_into_latest_features(
    tmp_path: Path,
) -> None:
    from src.data.research.archive_feature_contracts import (
        combined_source_snapshot_hash,
    )

    reader, manifests = _archive()
    identity = TwseCurrentSecurityIdentity(
        security_id=2330,
        symbol="2330",
        listing_date=START_DATE,
    )
    identities = TwseIdentitySnapshot(
        by_symbol={"2330": identity},
        snapshot_sha256=identity_snapshot_hash({"2330": identity}),
    )
    current_date = END_DATE + timedelta(days=1)
    publication = _publication_snapshot(current_date)
    publication_manifest = publication.manifest
    combined_hash = combined_source_snapshot_hash(
        historical_archive_snapshot_sha256=manifests.snapshot_sha256,
        publication_snapshot_sha256=publication_manifest.snapshot_sha256,
    )
    output = tmp_path / "twse-current-features.parquet"
    writer = TwseArchiveFeatureParquetWriter(
        output,
        dataset_snapshot_sha256=dataset_snapshot_hash(
            source_archive_snapshot_sha256=combined_hash,
            current_identity_snapshot_sha256=identities.snapshot_sha256,
        ),
        source_archive_snapshot_sha256=combined_hash,
        current_identity_snapshot_sha256=identities.snapshot_sha256,
    )

    audit = TwseArchiveFeatureDatasetBuilder(
        reader,
        now_fn=lambda: OBSERVED_AT,
    ).build(
        manifests=manifests,
        identities=identities,
        writer=writer,
        publication_snapshot=publication,
    )

    table = pq.read_table(output)
    assert audit.latest_decision_date == current_date
    assert audit.publication_snapshot_id == 91
    assert audit.publication_row_count == 1
    assert audit.source_archive_snapshot_sha256 == combined_hash
    assert table["decision_date"][-1].as_py() == current_date
    assert table["latest_available_at"][-1].as_py() <= table["decision_at"][-1].as_py()
    assert table["latest_observed_available_at"][-1].as_py() == OBSERVED_AT
    assert table["decision_close_price"][-1].as_py() == 172.0
    assert table["archive_id"][-1].as_py() == 91
    reasons = json.loads(table["reason_codes"][-1].as_py())
    assert "DAILY_BAR_PUBLICATION_RESEARCH_ONLY" in reasons


def test_builder_deterministically_prefers_archive_over_overlapping_publication(
    tmp_path: Path,
) -> None:
    from src.data.research.archive_feature_contracts import (
        combined_source_snapshot_hash,
    )

    reader, manifests = _archive()
    identity = TwseCurrentSecurityIdentity(
        security_id=2330,
        symbol="2330",
        listing_date=START_DATE,
    )
    identities = TwseIdentitySnapshot(
        by_symbol={"2330": identity},
        snapshot_sha256=identity_snapshot_hash({"2330": identity}),
    )
    publication = _publication_snapshot(END_DATE)
    combined_hash = combined_source_snapshot_hash(
        historical_archive_snapshot_sha256=manifests.snapshot_sha256,
        publication_snapshot_sha256=publication.manifest.snapshot_sha256,
    )
    output = tmp_path / "twse-overlap-features.parquet"
    writer = TwseArchiveFeatureParquetWriter(
        output,
        dataset_snapshot_sha256=dataset_snapshot_hash(
            source_archive_snapshot_sha256=combined_hash,
            current_identity_snapshot_sha256=identities.snapshot_sha256,
        ),
        source_archive_snapshot_sha256=combined_hash,
        current_identity_snapshot_sha256=identities.snapshot_sha256,
    )

    audit = TwseArchiveFeatureDatasetBuilder(
        reader,
        now_fn=lambda: OBSERVED_AT,
    ).build(
        manifests=manifests,
        identities=identities,
        writer=writer,
        publication_snapshot=publication,
    )

    table = pq.read_table(output)
    decision_dates = table["decision_date"].to_pylist()
    assert decision_dates == sorted(decision_dates)
    assert len(decision_dates) == len(set(decision_dates))
    assert audit.source_row_count == 73
    assert audit.parsed_source_row_count == 73
    assert audit.output_row_count == 12
    assert audit.latest_decision_date == END_DATE
    assert audit.exclusion_reason_counts["DAILY_PUBLICATION_OVERLAPS_ARCHIVE"] == 1
    assert set(table["archive_id"].to_pylist()) == {1}
    assert all(
        "DAILY_BAR_PUBLICATION_RESEARCH_ONLY" not in json.loads(value)
        for value in table["reason_codes"].to_pylist()
    )


def test_builder_excludes_hard_fail_rows_and_aborts_when_none_remain(
    tmp_path: Path,
) -> None:
    identity = TwseCurrentSecurityIdentity(
        security_id=2330,
        symbol="2330",
        listing_date=START_DATE,
    )
    identities = TwseIdentitySnapshot(
        by_symbol={"2330": identity},
        snapshot_sha256=identity_snapshot_hash({"2330": identity}),
    )
    source_rows = [_row(index) for index in range(72)]
    source_rows[-1]["high_price"] = "0"
    reader, manifests = _archive(source_rows)
    output = tmp_path / "twse-one-hard-fail.parquet"
    writer = TwseArchiveFeatureParquetWriter(
        output,
        dataset_snapshot_sha256=dataset_snapshot_hash(
            source_archive_snapshot_sha256=manifests.snapshot_sha256,
            current_identity_snapshot_sha256=identities.snapshot_sha256,
        ),
        source_archive_snapshot_sha256=manifests.snapshot_sha256,
        current_identity_snapshot_sha256=identities.snapshot_sha256,
    )

    audit = TwseArchiveFeatureDatasetBuilder(reader).build(
        manifests=manifests,
        identities=identities,
        writer=writer,
    )

    table = pq.read_table(output)
    assert audit.output_row_count == 11
    assert audit.exclusion_reason_counts["FEATURE_INPUT_INVALID:high_price"] == 1
    assert END_DATE not in table["decision_date"].to_pylist()
    assert set(table["hard_fail"].to_pylist()) == {False}

    all_invalid_rows = [_row(index) for index in range(72)]
    for row in all_invalid_rows:
        row["high_price"] = "0"
    invalid_reader, invalid_manifests = _archive(all_invalid_rows)
    failed_output = tmp_path / "twse-all-hard-fail.parquet"
    failed_writer = TwseArchiveFeatureParquetWriter(
        failed_output,
        dataset_snapshot_sha256=dataset_snapshot_hash(
            source_archive_snapshot_sha256=invalid_manifests.snapshot_sha256,
            current_identity_snapshot_sha256=identities.snapshot_sha256,
        ),
        source_archive_snapshot_sha256=invalid_manifests.snapshot_sha256,
        current_identity_snapshot_sha256=identities.snapshot_sha256,
    )

    with pytest.raises(TwseArchiveFeatureBuildError) as captured:
        _ = TwseArchiveFeatureDatasetBuilder(invalid_reader).build(
            manifests=invalid_manifests,
            identities=identities,
            writer=failed_writer,
        )

    assert captured.value.reason_code == "TWSE_RESEARCH_FEATURE_ROWS_EMPTY"
    assert not failed_output.exists()
    assert not failed_writer.partial_path.exists()


def test_builder_aborts_for_incomplete_or_cross_market_sources(
    tmp_path: Path,
) -> None:
    from src.data.research.archive_feature_contracts import (
        combined_source_snapshot_hash,
    )

    reader, complete_manifests = _archive()
    identity = TwseCurrentSecurityIdentity(
        security_id=2330,
        symbol="2330",
        listing_date=START_DATE,
    )
    identities = TwseIdentitySnapshot(
        by_symbol={"2330": identity},
        snapshot_sha256=identity_snapshot_hash({"2330": identity}),
    )
    incomplete_manifests = HistoricalArchiveManifestSnapshot(
        rows=complete_manifests.rows,
        snapshot_sha256=complete_manifests.snapshot_sha256,
        complete=False,
    )
    incomplete_output = tmp_path / "twse-incomplete.parquet"
    incomplete_writer = TwseArchiveFeatureParquetWriter(
        incomplete_output,
        dataset_snapshot_sha256=dataset_snapshot_hash(
            source_archive_snapshot_sha256=incomplete_manifests.snapshot_sha256,
            current_identity_snapshot_sha256=identities.snapshot_sha256,
        ),
        source_archive_snapshot_sha256=incomplete_manifests.snapshot_sha256,
        current_identity_snapshot_sha256=identities.snapshot_sha256,
    )

    with pytest.raises(TwseArchiveFeatureBuildError) as incomplete_error:
        _ = TwseArchiveFeatureDatasetBuilder(reader).build(
            manifests=incomplete_manifests,
            identities=identities,
            writer=incomplete_writer,
        )

    assert incomplete_error.value.reason_code == "MANIFEST_SNAPSHOT_INCOMPLETE"
    assert not incomplete_output.exists()
    assert not incomplete_writer.partial_path.exists()

    tpex_publication = _publication_snapshot(
        END_DATE + timedelta(days=1),
        market="TPEX",
        security_id=5483,
        symbol="5483",
    )
    combined_hash = combined_source_snapshot_hash(
        historical_archive_snapshot_sha256=complete_manifests.snapshot_sha256,
        publication_snapshot_sha256=tpex_publication.manifest.snapshot_sha256,
    )
    scope_output = tmp_path / "twse-cross-market.parquet"
    scope_writer = TwseArchiveFeatureParquetWriter(
        scope_output,
        dataset_snapshot_sha256=dataset_snapshot_hash(
            source_archive_snapshot_sha256=combined_hash,
            current_identity_snapshot_sha256=identities.snapshot_sha256,
        ),
        source_archive_snapshot_sha256=combined_hash,
        current_identity_snapshot_sha256=identities.snapshot_sha256,
    )

    with pytest.raises(TwseArchiveFeatureBuildError) as scope_error:
        _ = TwseArchiveFeatureDatasetBuilder(reader).build(
            manifests=complete_manifests,
            identities=identities,
            writer=scope_writer,
            publication_snapshot=tpex_publication,
        )

    assert scope_error.value.reason_code == "TWSE_DAILY_PUBLICATION_SCOPE_MISMATCH"
    assert not scope_output.exists()
    assert not scope_writer.partial_path.exists()
