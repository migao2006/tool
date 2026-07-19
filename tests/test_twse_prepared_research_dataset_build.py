from __future__ import annotations

# pyright: reportAny=false, reportMissingTypeStubs=false

from dataclasses import asdict
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.data.archive.contracts import (
    HistoricalArchiveManifest,
    VerifiedHistoricalArchive,
)
from src.data.archive.manifest_repository import HistoricalArchiveManifestSnapshot
from src.data.ingestion.historical_archive_contracts import (
    HISTORICAL_ARCHIVE_SCHEMA_VERSION,
)
from src.data.ingestion.taiex_ohlc_contracts import TAIEX_OHLC_SCHEMA_VERSION
from src.data.providers.twse import TAIEX_MONTHLY_OHLC_DATASET
from src.data.research.twse_archive_feature_contracts import dataset_snapshot_hash
from src.data.research.twse_archive_feature_parquet import (
    TwseArchiveFeatureParquetWriter,
)
from src.data.research.twse_feature_artifact_reader import TwseFeatureArtifactReader
from src.features.twse_price_volume_schema import (
    TWSE_PRICE_VOLUME_FEATURE_NAMES,
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
    TWSE_PRICE_VOLUME_PRICE_BASIS,
)
from src.pipeline.twse_prepared_research_artifact import (
    PreparedResearchArtifactError,
    PreparedResearchArtifactWriter,
)
from src.pipeline.twse_research_dataset_build import (
    TwseResearchDatasetBuildError,
    TwseResearchDatasetBuilder,
)


TAIPEI = ZoneInfo("Asia/Taipei")
SESSIONS = tuple(value.date() for value in pd.bdate_range("2024-01-02", periods=8))
SOURCE_SNAPSHOT = "a" * 64
IDENTITY_SNAPSHOT = "b" * 64
DATASET_SNAPSHOT = dataset_snapshot_hash(
    source_archive_snapshot_sha256=SOURCE_SNAPSHOT,
    current_identity_snapshot_sha256=IDENTITY_SNAPSHOT,
)
BUCKET = "alpha-lens-archive"
DAILY_KEY = "raw/v1/daily/2330.parquet"
DAILY_HASH = "d" * 64


def _manifest(
    *,
    object_key: str,
    provider: str,
    dataset: str,
    symbol: str,
    asset_type: str,
    schema_version: str,
    parquet_hash: str,
    row_count: int,
) -> HistoricalArchiveManifest:
    return HistoricalArchiveManifest(
        archive_key=sha256(f"{BUCKET}\0{object_key}".encode()).hexdigest(),
        storage_provider="CLOUDFLARE_R2",
        bucket_name=BUCKET,
        object_key=object_key,
        object_etag='"etag"',
        schema_version=schema_version,
        provider_code=provider,
        source_dataset=dataset,
        source_version=(
            "rwd.en.TAIEX.MI_5MINS_HIST.v1" if provider == "TWSE" else "v1"
        ),
        source_symbol=symbol,
        scheduled_market="TWSE",
        asset_type=asset_type,
        requested_start_date=SESSIONS[0],
        requested_end_date=SESSIONS[-1],
        min_trade_date=SESSIONS[0],
        max_trade_date=SESSIONS[-1],
        source_payload_hash="c" * 64,
        parquet_sha256=parquet_hash,
        byte_size=100,
        row_count=row_count,
        parsed_row_count=row_count,
        quarantined_row_count=0,
        first_observed_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        point_in_time_status="UNVERIFIED",
        usage_scope="RAW_LANDING_ONLY",
        system_status="RESEARCH_ONLY",
        reason_codes=("POINT_IN_TIME_UNVERIFIED",),
    )


DAILY_MANIFEST = _manifest(
    object_key=DAILY_KEY,
    provider="FINMIND",
    dataset="daily_bars",
    symbol="2330",
    asset_type="COMMON_STOCK",
    schema_version=HISTORICAL_ARCHIVE_SCHEMA_VERSION,
    parquet_hash=DAILY_HASH,
    row_count=len(SESSIONS),
)
BENCHMARK_MANIFEST = _manifest(
    object_key="raw/v1/provider=twse/dataset=taiex_price_index_ohlc/2024-01.parquet",
    provider="TWSE",
    dataset=TAIEX_MONTHLY_OHLC_DATASET,
    symbol="TAIEX",
    asset_type="BENCHMARK",
    schema_version=TAIEX_OHLC_SCHEMA_VERSION,
    parquet_hash="e" * 64,
    row_count=len(SESSIONS),
)


def _snapshot(
    manifest: HistoricalArchiveManifest,
    *,
    archive_id: int,
    snapshot_hash: str,
) -> HistoricalArchiveManifestSnapshot:
    return HistoricalArchiveManifestSnapshot(
        rows=(MappingProxyType({"archive_id": archive_id, **asdict(manifest)}),),
        snapshot_sha256=snapshot_hash,
        complete=True,
    )


def _daily_rows() -> tuple[MappingProxyType[str, object], ...]:
    return tuple(
        MappingProxyType(
            {
                "parse_status": "PARSED",
                "trade_date": session,
                "open_price": str(100 + index),
                "close_price": str(100 + index),
            }
        )
        for index, session in enumerate(SESSIONS)
    )


def _benchmark_rows() -> tuple[MappingProxyType[str, object], ...]:
    return tuple(
        MappingProxyType(
            {
                "parse_status": "PARSED",
                "trade_date": session,
                "open_index": 1_000 + index * 2,
                "close_index": 1_001 + index * 2,
                "benchmark_semantics": "PRICE_INDEX_NOT_TOTAL_RETURN",
            }
        )
        for index, session in enumerate(SESSIONS)
    )


class _ArchiveReader:
    def read(self, manifest: HistoricalArchiveManifest) -> VerifiedHistoricalArchive:
        rows = (
            _daily_rows()
            if manifest.source_dataset == "daily_bars"
            else _benchmark_rows()
        )
        return VerifiedHistoricalArchive(
            manifest=manifest,
            rows=rows,
            content_sha256=manifest.parquet_sha256,
            byte_size=manifest.byte_size,
            row_count=manifest.row_count,
            schema_version=manifest.schema_version,
        )


def _feature_artifact(path: Path):
    decision_date = SESSIONS[0]
    row: dict[str, object] = {
        "dataset_snapshot_sha256": DATASET_SNAPSHOT,
        "source_archive_snapshot_sha256": SOURCE_SNAPSHOT,
        "current_identity_snapshot_sha256": IDENTITY_SNAPSHOT,
        "archive_id": 101,
        "source_object_key": DAILY_KEY,
        "source_payload_sha256": "c" * 64,
        "source_parquet_sha256": DAILY_HASH,
        "security_id": 2330,
        "listing_period_id": "CURRENT:TWSE:2330:1994-09-05:OPEN",
        "symbol": "2330",
        "market": "TWSE",
        "asset_type": "COMMON_STOCK",
        "listing_date": date(1994, 9, 5),
        "decision_date": decision_date,
        "decision_at": datetime(2024, 1, 2, 17, tzinfo=TAIPEI),
        "horizon": 5,
        "decision_time_policy_version": "twse-post-close-1700-asia-taipei-v1",
        "feature_schema_version": TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
        "feature_schema_hash": TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
        "price_basis": TWSE_PRICE_VOLUME_PRICE_BASIS,
        "availability_mode": "RESEARCH_SCHEDULING_HINT",
        "latest_available_at": datetime(2024, 1, 2, 16, tzinfo=TAIPEI),
        "latest_observed_available_at": datetime(2026, 7, 19, tzinfo=timezone.utc),
        "point_in_time_audit_pass": False,
        "hard_fail": False,
        "research_limitation_reason_codes": ["RESEARCH_SCHEDULING_HINT"],
        "hard_fail_reason_codes": [],
        "label_status": "LABELS_NOT_ASSEMBLED",
        "usage_scope": "FEATURE_RESEARCH_ONLY",
        "system_status": "RESEARCH_ONLY",
        "reason_codes": json.dumps(["RESEARCH_SCHEDULING_HINT"]),
        "source_reason_codes": json.dumps(["POINT_IN_TIME_UNVERIFIED"]),
    }
    row.update(
        {
            name: (100_000_000.0 if name == "adv20_ntd" else float(index + 1))
            for index, name in enumerate(TWSE_PRICE_VOLUME_FEATURE_NAMES)
        }
    )
    writer = TwseArchiveFeatureParquetWriter(
        path,
        dataset_snapshot_sha256=DATASET_SNAPSHOT,
        source_archive_snapshot_sha256=SOURCE_SNAPSHOT,
        current_identity_snapshot_sha256=IDENTITY_SNAPSHOT,
    )
    writer.write_rows([row])
    writer.finish()
    reader = TwseFeatureArtifactReader()
    return reader.verify(path, reader.manifest_from_parquet(path))


def _result(tmp_path: Path):
    return TwseResearchDatasetBuilder(  # pyright: ignore[reportArgumentType]
        _ArchiveReader()
    ).build(
        daily_manifests=_snapshot(
            DAILY_MANIFEST,
            archive_id=101,
            snapshot_hash=SOURCE_SNAPSHOT,
        ),
        benchmark_manifests=_snapshot(
            BENCHMARK_MANIFEST,
            archive_id=201,
            snapshot_hash="f" * 64,
        ),
        feature_artifact=_feature_artifact(tmp_path / "features.parquet"),
    )


def test_builder_uses_aligned_taiex_ohlc_and_preserves_research_limits(
    tmp_path: Path,
) -> None:
    result = _result(tmp_path)

    assert result.assembly.audit.prepared_row_count == 1
    row = result.assembly.prepared_rows.iloc[0]
    assert row["benchmark_return"] == pytest.approx(1_011 / 1_002 - 1)
    assert "BENCHMARK_PRICE_INDEX_NOT_TOTAL_RETURN" in (
        result.assembly.audit.audit_reason_codes
    )
    assert "BENCHMARK_CLOSE_TO_CLOSE_NOT_EXECUTION_PATH_ALIGNED" not in (
        result.assembly.audit.audit_reason_codes
    )
    assert result.audit_payload()["system_status"] == "RESEARCH_ONLY"


def test_builder_rejects_unsupported_horizon_and_snapshot_mismatch(
    tmp_path: Path,
) -> None:
    artifact = _feature_artifact(tmp_path / "features.parquet")
    builder = TwseResearchDatasetBuilder(  # pyright: ignore[reportArgumentType]
        _ArchiveReader()
    )
    with pytest.raises(TwseResearchDatasetBuildError) as unsupported:
        builder.build(
            daily_manifests=_snapshot(
                DAILY_MANIFEST, archive_id=101, snapshot_hash=SOURCE_SNAPSHOT
            ),
            benchmark_manifests=_snapshot(
                BENCHMARK_MANIFEST, archive_id=201, snapshot_hash="f" * 64
            ),
            feature_artifact=artifact,
            horizon=3,
        )
    assert unsupported.value.reason_code == "UNSUPPORTED_HORIZON"

    with pytest.raises(TwseResearchDatasetBuildError) as mismatch:
        builder.build(
            daily_manifests=_snapshot(
                DAILY_MANIFEST, archive_id=101, snapshot_hash="0" * 64
            ),
            benchmark_manifests=_snapshot(
                BENCHMARK_MANIFEST, archive_id=201, snapshot_hash="f" * 64
            ),
            feature_artifact=artifact,
        )
    assert mismatch.value.reason_code == "FEATURE_DAILY_ARCHIVE_SNAPSHOT_MISMATCH"


def test_prepared_writer_roundtrips_and_detects_replacement(tmp_path: Path) -> None:
    result = _result(tmp_path)
    output = tmp_path / "prepared.parquet"
    writer = PreparedResearchArtifactWriter()

    manifest = writer.write(output, result)
    dataset = writer.verify(output, manifest)

    assert manifest.system_status == "RESEARCH_ONLY"
    assert manifest.benchmark_path == "T_PLUS_ONE_OPEN_TO_H_CLOSE"
    assert dataset.frame.iloc[0]["symbol"] == "2330"

    output.write_bytes(output.read_bytes() + b"tampered")
    with pytest.raises(PreparedResearchArtifactError) as captured:
        _ = writer.verify(output, manifest)
    assert captured.value.reason_code == "PREPARED_RESEARCH_ARTIFACT_MANIFEST_MISMATCH"
