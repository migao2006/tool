from __future__ import annotations

# pyright: reportAny=false, reportMissingTypeStubs=false

from collections.abc import Mapping
from dataclasses import asdict, replace
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
from src.data.ingestion.tpex_ohlc_contracts import TPEX_OHLC_SCHEMA_VERSION
from src.data.providers.tpex import TPEX_MONTHLY_OHLC_DATASET
from src.data.research.tpex_archive_feature_contracts import dataset_snapshot_hash
from src.data.research.tpex_archive_feature_parquet import (
    TpexArchiveFeatureParquetWriter,
)
from src.data.research.tpex_feature_artifact_reader import TpexFeatureArtifactReader
from src.features.tpex_price_volume_schema import (
    TPEX_PRICE_VOLUME_FEATURE_NAMES,
    TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
    TPEX_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
    TPEX_PRICE_VOLUME_PRICE_BASIS,
)
from src.pipeline.contracts import PipelineMode
from src.pipeline.tpex_research_dataset_build import (
    TPEX_DAILY_BAR_FILTERS,
    TPEX_OHLC_FILTERS,
    TpexResearchDatasetBuildError,
    TpexResearchDatasetBuilder,
)
from src.pipeline.twse_prepared_research_artifact import (
    PreparedResearchArtifactWriter,
)
from src.pipeline.twse_prepared_research_repository import (
    PreparedResearchArtifactRepository,
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
DAILY_KEY = "raw/v1/daily/6488.parquet"
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
    is_benchmark = asset_type == "BENCHMARK"
    return HistoricalArchiveManifest(
        archive_key=sha256(f"{BUCKET}\0{object_key}".encode()).hexdigest(),
        storage_provider="CLOUDFLARE_R2",
        bucket_name=BUCKET,
        object_key=object_key,
        object_etag='"etag"',
        schema_version=schema_version,
        provider_code=provider,
        source_dataset=dataset,
        source_version=("tpex.inxh.monthly.v1" if is_benchmark else "v1"),
        source_symbol=symbol,
        scheduled_market="TPEX",
        asset_type=asset_type,
        requested_start_date=date(2024, 1, 1) if is_benchmark else SESSIONS[0],
        requested_end_date=date(2024, 1, 31) if is_benchmark else SESSIONS[-1],
        min_trade_date=SESSIONS[0],
        max_trade_date=SESSIONS[-1],
        source_payload_hash="c" * 64,
        parquet_sha256=parquet_hash,
        byte_size=100,
        row_count=row_count,
        parsed_row_count=row_count,
        quarantined_row_count=0,
        first_observed_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        point_in_time_status="UNVERIFIED",
        usage_scope="RAW_LANDING_ONLY",
        system_status="RESEARCH_ONLY",
        reason_codes=("POINT_IN_TIME_UNVERIFIED",),
    )


DAILY_MANIFEST = _manifest(
    object_key=DAILY_KEY,
    provider="FINMIND",
    dataset="daily_bars",
    symbol="6488",
    asset_type="COMMON_STOCK",
    schema_version=HISTORICAL_ARCHIVE_SCHEMA_VERSION,
    parquet_hash=DAILY_HASH,
    row_count=len(SESSIONS),
)
BENCHMARK_MANIFEST = _manifest(
    object_key="raw/v1/provider=tpex/dataset=tpex_price_index_ohlc/2024-01.parquet",
    provider="TPEX",
    dataset=TPEX_MONTHLY_OHLC_DATASET,
    symbol="TPEX_INDEX",
    asset_type="BENCHMARK",
    schema_version=TPEX_OHLC_SCHEMA_VERSION,
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


class _ArchiveReader:
    def read(self, manifest: HistoricalArchiveManifest) -> VerifiedHistoricalArchive:
        if manifest.source_dataset == "daily_bars":
            rows = tuple(
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
        else:
            rows = tuple(
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
        return VerifiedHistoricalArchive(
            manifest=manifest,
            rows=rows,
            content_sha256=manifest.parquet_sha256,
            byte_size=manifest.byte_size,
            row_count=manifest.row_count,
            schema_version=manifest.schema_version,
        )


def _feature_artifact(
    path: Path,
    *,
    row_overrides: Mapping[str, object] | None = None,
):
    row: dict[str, object] = {
        "dataset_snapshot_sha256": DATASET_SNAPSHOT,
        "source_archive_snapshot_sha256": SOURCE_SNAPSHOT,
        "current_identity_snapshot_sha256": IDENTITY_SNAPSHOT,
        "archive_id": 101,
        "source_object_key": DAILY_KEY,
        "source_payload_sha256": "c" * 64,
        "source_parquet_sha256": DAILY_HASH,
        "security_id": 6488,
        "listing_period_id": "CURRENT:TPEX:6488:2018-03-29:OPEN",
        "symbol": "6488",
        "market": "TPEX",
        "asset_type": "COMMON_STOCK",
        "listing_date": date(2018, 3, 29),
        "decision_date": SESSIONS[0],
        "decision_at": datetime(2024, 1, 2, 17, tzinfo=TAIPEI),
        "horizon": 5,
        "decision_time_policy_version": "tpex-post-close-1700-asia-taipei-v1",
        "feature_schema_version": TPEX_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
        "feature_schema_hash": TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
        "price_basis": TPEX_PRICE_VOLUME_PRICE_BASIS,
        "availability_mode": "RESEARCH_SCHEDULING_HINT",
        "decision_close_price": 100.0,
        "latest_available_at": datetime(2024, 1, 2, 16, tzinfo=TAIPEI),
        "latest_observed_available_at": datetime(2026, 7, 20, tzinfo=timezone.utc),
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
            for index, name in enumerate(TPEX_PRICE_VOLUME_FEATURE_NAMES)
        }
    )
    row.update(row_overrides or {})
    writer = TpexArchiveFeatureParquetWriter(
        path,
        dataset_snapshot_sha256=DATASET_SNAPSHOT,
        source_archive_snapshot_sha256=SOURCE_SNAPSHOT,
        current_identity_snapshot_sha256=IDENTITY_SNAPSHOT,
    )
    writer.write_rows([row])
    writer.finish()
    reader = TpexFeatureArtifactReader()
    return reader.verify(path, reader.manifest_from_parquet(path))


def _result(tmp_path: Path, *, benchmark_hash: str = "f" * 64):
    tmp_path.mkdir(parents=True, exist_ok=True)
    return TpexResearchDatasetBuilder(  # pyright: ignore[reportArgumentType]
        _ArchiveReader()
    ).build(
        daily_manifests=_snapshot(
            DAILY_MANIFEST, archive_id=101, snapshot_hash=SOURCE_SNAPSHOT
        ),
        benchmark_manifests=_snapshot(
            BENCHMARK_MANIFEST, archive_id=201, snapshot_hash=benchmark_hash
        ),
        feature_artifact=_feature_artifact(tmp_path / "features.parquet"),
    )


def test_tpex_builder_uses_same_open_close_path_and_preserves_limits(
    tmp_path: Path,
) -> None:
    result = _result(tmp_path)
    row = result.assembly.prepared_rows.iloc[0]

    assert result.assembly.audit.market == "TPEX"
    assert row["market"] == "TPEX"
    assert row["benchmark_return"] == pytest.approx(1_011 / 1_002 - 1)
    assert row["gross_return"] == pytest.approx(105 / 101 - 1)
    assert row["label_version"].startswith("tpex-research-")
    assert "TRADING_CALENDAR_DERIVED_FROM_BENCHMARK_RESEARCH_ONLY" in (
        result.assembly.audit.audit_reason_codes
    )
    assert result.audit_payload()["system_status"] == "RESEARCH_ONLY"


def test_tpex_builder_rejects_horizon_and_feature_lineage(tmp_path: Path) -> None:
    builder = TpexResearchDatasetBuilder(  # pyright: ignore[reportArgumentType]
        _ArchiveReader()
    )
    arguments = {
        "daily_manifests": _snapshot(
            DAILY_MANIFEST, archive_id=101, snapshot_hash=SOURCE_SNAPSHOT
        ),
        "benchmark_manifests": _snapshot(
            BENCHMARK_MANIFEST, archive_id=201, snapshot_hash="f" * 64
        ),
    }
    with pytest.raises(TpexResearchDatasetBuildError) as unsupported:
        builder.build(
            **arguments,
            feature_artifact=_feature_artifact(tmp_path / "horizon.parquet"),
            horizon=3,
        )
    assert unsupported.value.reason_code == "UNSUPPORTED_HORIZON"

    with pytest.raises(TpexResearchDatasetBuildError) as lineage:
        builder.build(
            **arguments,
            feature_artifact=_feature_artifact(
                tmp_path / "lineage.parquet", row_overrides={"archive_id": 999}
            ),
        )
    assert lineage.value.reason_code == "FEATURE_DAILY_ARCHIVE_LINEAGE_MISMATCH"


def test_tpex_prepared_artifact_is_market_typed_and_read_back_verified(
    tmp_path: Path,
) -> None:
    result = _result(tmp_path / "input")
    output = tmp_path / "tpex-prepared.parquet"
    audit = tmp_path / "tpex-prepared-audit.json"
    writer = PreparedResearchArtifactWriter()
    manifest = writer.write(output, result)
    payload = result.audit_payload()
    payload.update(
        {
            "output_file": output.name,
            "prepared_artifact_manifest": manifest.to_dict(),
            "prepared_artifact_read_back_verified": True,
        }
    )
    _ = audit.write_text(json.dumps(payload), encoding="utf-8")

    assert manifest.market == "TPEX"
    assert manifest.artifact_version == "tpex-prepared-research-5d.v1"
    batch = PreparedResearchArtifactRepository(
        output, audit, expected_market="TPEX"
    ).load(mode=PipelineMode.TRAIN, horizon=5, as_of_date=None)
    assert len(batch.records) == 1
    with pytest.raises(ValueError):
        _ = replace(manifest, benchmark_snapshot_sha256="7" * 64)


def test_tpex_manifest_filters_are_exact_and_snapshots_change(tmp_path: Path) -> None:
    assert TPEX_DAILY_BAR_FILTERS == {
        "provider_code": "eq.FINMIND",
        "source_dataset": "eq.daily_bars",
        "scheduled_market": "eq.TPEX",
        "asset_type": "eq.COMMON_STOCK",
    }
    assert TPEX_OHLC_FILTERS["provider_code"] == "eq.TPEX"
    assert TPEX_OHLC_FILTERS["source_symbol"] == "eq.TPEX_INDEX"
    first = _result(tmp_path / "first", benchmark_hash="f" * 64)
    second = _result(tmp_path / "second", benchmark_hash="9" * 64)
    assert (
        first.prepared_dataset_snapshot_sha256
        != second.prepared_dataset_snapshot_sha256
    )
