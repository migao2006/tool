from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pyarrow.parquet as pq
import pandas as pd
import pytest

from src.data.archive.historical_parquet_reader import HistoricalParquetReader
from src.data.archive.manifest_repository import HistoricalArchiveManifestSnapshot
from src.data.ingestion.historical_archive_contracts import HistoricalArchiveRequest
from src.data.ingestion.historical_parquet_serializer import (
    serialize_historical_parquet,
)
from src.data.object_storage.r2_client import R2Client, R2Settings
from src.data.research.twse_archive_feature_builder import (
    TwseArchiveFeatureBuildError,
    TwseArchiveFeatureDatasetBuilder,
)
from src.data.research.twse_archive_feature_contracts import (
    TwseCurrentSecurityIdentity,
    TwseIdentitySnapshot,
    dataset_snapshot_hash,
    identity_snapshot_hash,
)
from src.data.research.twse_archive_feature_parquet import (
    TwseArchiveFeatureParquetWriter,
)
from src.pipeline.twse_research_assembly_inputs import feature_records, reason_codes


OBSERVED_AT = datetime(2026, 7, 19, 4, tzinfo=timezone.utc)
START_DATE = date(2021, 1, 1)
END_DATE = START_DATE + timedelta(days=71)
SOURCE_PAYLOAD_HASH = "c" * 64
BUCKET = "alpha-lens-archive"


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


def _archive() -> tuple[HistoricalParquetReader, HistoricalArchiveManifestSnapshot]:
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
        [_row(index) for index in range(72)],
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
    assert "net_return" not in table.column_names
    assert "alpha" not in table.column_names
    assert set(table["label_status"].to_pylist()) == {"LABELS_NOT_ASSEMBLED"}
    assert set(table["availability_mode"].to_pylist()) == {"RESEARCH_SCHEDULING_HINT"}
    assert set(table["point_in_time_audit_pass"].to_pylist()) == {False}
    assert (
        "RESEARCH_SCHEDULING_HINT"
        in table["research_limitation_reason_codes"][0].as_py()
    )
    reasons = json.loads(table["reason_codes"][0].as_py())
    assert "LABELS_NOT_ASSEMBLED" in reasons
    assert "IDENTITY_UNRESOLVED" in reasons
    assert parquet.schema_arrow.metadata[b"system.status"] == b"RESEARCH_ONLY"
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
