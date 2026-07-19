from __future__ import annotations

# pyright: reportAny=false, reportMissingTypeStubs=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from dataclasses import replace
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
import pytest

from src.data.research.twse_archive_feature_contracts import dataset_snapshot_hash
from src.data.research.twse_archive_feature_parquet import (
    TwseArchiveFeatureParquetWriter,
)
from src.data.research.twse_feature_artifact_contracts import (
    TwseFeatureArtifactManifest,
    TwseFeatureArtifactReadError,
    VerifiedTwseFeatureArtifact,
)
from src.data.research.twse_feature_artifact_reader import (
    TwseFeatureArtifactReader,
)
from src.features.twse_price_volume_schema import (
    TWSE_PRICE_VOLUME_FEATURE_NAMES,
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
    TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
    TWSE_PRICE_VOLUME_PRICE_BASIS,
)
from src.pipeline.twse_feature_artifact_input import (
    feature_artifact_assembly_input,
)


SOURCE_SNAPSHOT = "a" * 64
IDENTITY_SNAPSHOT = "b" * 64
DATASET_SNAPSHOT = dataset_snapshot_hash(
    source_archive_snapshot_sha256=SOURCE_SNAPSHOT,
    current_identity_snapshot_sha256=IDENTITY_SNAPSHOT,
)


def _feature_row(
    *,
    dataset_snapshot: str = DATASET_SNAPSHOT,
    feature_offset: float = 0.0,
    source_payload_sha256: str = "c" * 64,
) -> dict[str, object]:
    row: dict[str, object] = {
        "dataset_snapshot_sha256": dataset_snapshot,
        "source_archive_snapshot_sha256": SOURCE_SNAPSHOT,
        "current_identity_snapshot_sha256": IDENTITY_SNAPSHOT,
        "archive_id": 101,
        "source_object_key": "historical/finmind/daily_bars/TWSE/2330.parquet",
        "source_payload_sha256": source_payload_sha256,
        "source_parquet_sha256": "d" * 64,
        "security_id": 2330,
        "listing_period_id": "CURRENT:TWSE:2330:1994-09-05:OPEN",
        "symbol": "2330",
        "market": "TWSE",
        "asset_type": "COMMON_STOCK",
        "listing_date": date(1994, 9, 5),
        "decision_date": date(2026, 7, 17),
        "decision_at": datetime(
            2026,
            7,
            17,
            17,
            tzinfo=ZoneInfo("Asia/Taipei"),
        ),
        "horizon": 5,
        "decision_time_policy_version": "twse-post-close-1700-asia-taipei-v1",
        "feature_schema_version": TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
        "feature_schema_hash": TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
        "price_basis": TWSE_PRICE_VOLUME_PRICE_BASIS,
        "availability_mode": "RESEARCH_SCHEDULING_HINT",
        "latest_available_at": datetime(2026, 7, 17, 8, tzinfo=timezone.utc),
        "latest_observed_available_at": datetime(
            2026,
            7,
            19,
            4,
            tzinfo=timezone.utc,
        ),
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
            name: float(index + 1) + feature_offset
            for index, name in enumerate(TWSE_PRICE_VOLUME_FEATURE_NAMES)
        }
    )
    return row


def _write_artifact(
    path: Path,
    *,
    dataset_snapshot: str = DATASET_SNAPSHOT,
    feature_offset: float = 0.0,
    source_payload_sha256: str = "c" * 64,
) -> None:
    writer = TwseArchiveFeatureParquetWriter(
        path,
        dataset_snapshot_sha256=dataset_snapshot,
        source_archive_snapshot_sha256=SOURCE_SNAPSHOT,
        current_identity_snapshot_sha256=IDENTITY_SNAPSHOT,
    )
    writer.write_rows(
        [
            _feature_row(
                dataset_snapshot=dataset_snapshot,
                feature_offset=feature_offset,
                source_payload_sha256=source_payload_sha256,
            )
        ]
    )
    writer.finish()


def test_manifest_is_derived_from_parquet_bytes_and_read_back_verified(
    tmp_path: Path,
) -> None:
    output = tmp_path / "twse-features.parquet"
    _write_artifact(output)
    reader = TwseFeatureArtifactReader()

    manifest = reader.manifest_from_parquet(output)
    verified = reader.verify(output, manifest)
    table = reader.read_table(verified)

    assert manifest.parquet_sha256 == sha256(output.read_bytes()).hexdigest()
    assert manifest.byte_size == output.stat().st_size
    assert manifest.row_count == 1
    assert manifest.dataset_snapshot_sha256 == DATASET_SNAPSHOT
    assert manifest.parquet_schema_sha256 != manifest.feature_schema_hash
    assert manifest.point_in_time_status == "UNVERIFIED"
    assert verified.point_in_time_verified is False
    assert table.num_rows == 1
    assert TwseFeatureArtifactManifest.from_mapping(manifest.to_dict()) == manifest


def test_manifest_mismatch_fails_closed(tmp_path: Path) -> None:
    output = tmp_path / "twse-features.parquet"
    _write_artifact(output)
    reader = TwseFeatureArtifactReader()
    manifest = reader.manifest_from_parquet(output)

    with pytest.raises(TwseFeatureArtifactReadError) as captured:
        _ = reader.verify(
            output,
            replace(manifest, parquet_sha256="f" * 64),
        )

    assert captured.value.reason_code == "TWSE_FEATURE_ARTIFACT_MANIFEST_MISMATCH"


def test_read_table_detects_artifact_replacement_after_verification(
    tmp_path: Path,
) -> None:
    output = tmp_path / "twse-features.parquet"
    _write_artifact(output)
    reader = TwseFeatureArtifactReader()
    verified = reader.verify(output, reader.manifest_from_parquet(output))

    _write_artifact(output, feature_offset=10.0)

    with pytest.raises(TwseFeatureArtifactReadError) as captured:
        _ = reader.read_table(verified)

    assert (
        captured.value.reason_code == "TWSE_FEATURE_ARTIFACT_CHANGED_AFTER_VERIFICATION"
    )


def test_snapshot_and_schema_tampering_are_rejected(tmp_path: Path) -> None:
    snapshot_output = tmp_path / "bad-snapshot.parquet"
    _write_artifact(snapshot_output, dataset_snapshot="e" * 64)
    reader = TwseFeatureArtifactReader()

    with pytest.raises(TwseFeatureArtifactReadError) as snapshot_error:
        _ = reader.manifest_from_parquet(snapshot_output)
    assert (
        snapshot_error.value.reason_code
        == "TWSE_FEATURE_ARTIFACT_INPUT_SNAPSHOT_MISMATCH"
    )

    schema_output = tmp_path / "bad-schema.parquet"
    _write_artifact(schema_output)
    table = pq.read_table(schema_output).drop([TWSE_PRICE_VOLUME_FEATURE_NAMES[0]])
    pq.write_table(table, schema_output)

    with pytest.raises(TwseFeatureArtifactReadError) as schema_error:
        _ = reader.manifest_from_parquet(schema_output)
    assert schema_error.value.reason_code == "TWSE_FEATURE_ARTIFACT_SCHEMA_INVALID"


def test_invalid_row_lineage_is_rejected(tmp_path: Path) -> None:
    output = tmp_path / "invalid-lineage.parquet"
    _write_artifact(output, source_payload_sha256="G" * 64)

    with pytest.raises(TwseFeatureArtifactReadError) as captured:
        _ = TwseFeatureArtifactReader().manifest_from_parquet(output)

    assert captured.value.reason_code == "TWSE_FEATURE_ARTIFACT_LINEAGE_INVALID"


def test_only_reader_can_construct_verified_artifact(tmp_path: Path) -> None:
    output = tmp_path / "twse-features.parquet"
    _write_artifact(output)
    manifest = TwseFeatureArtifactReader().manifest_from_parquet(output)

    with pytest.raises(TypeError):
        _ = VerifiedTwseFeatureArtifact(
            path=output,
            manifest=manifest,
            _proof=object(),
        )


def test_assembly_input_derives_provenance_from_verified_bytes(
    tmp_path: Path,
) -> None:
    output = tmp_path / "twse-features.parquet"
    _write_artifact(output)
    reader = TwseFeatureArtifactReader()
    artifact = reader.verify(output, reader.manifest_from_parquet(output))

    bound = feature_artifact_assembly_input(artifact, reader=reader)

    assert bound.dataset_snapshot_id == DATASET_SNAPSHOT
    assert bound.source_hash == artifact.manifest.parquet_sha256
    assert list(bound.feature_rows["symbol"]) == ["2330"]

    with pytest.raises(TypeError):
        _ = feature_artifact_assembly_input(
            artifact.manifest  # pyright: ignore[reportArgumentType]
        )
