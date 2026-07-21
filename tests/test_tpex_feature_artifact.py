from __future__ import annotations

# pyright: reportAny=false, reportMissingTypeStubs=false
# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false

from dataclasses import replace
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
import pytest

from src.data.research.tpex_archive_feature_contracts import dataset_snapshot_hash
from src.data.research.tpex_archive_feature_parquet import (
    TpexArchiveFeatureParquetWriter,
)
from src.data.research.tpex_feature_artifact_contracts import (
    TPEX_FEATURE_ARTIFACT_MANIFEST_VERSION,
    TpexFeatureArtifactManifest,
    TpexFeatureArtifactReadError,
    VerifiedTpexFeatureArtifact,
)
from src.data.research.tpex_feature_artifact_reader import (
    TpexFeatureArtifactReader,
)
from src.data.research.twse_feature_artifact_contracts import (
    TwseFeatureArtifactReadError,
)
from src.data.research.twse_feature_artifact_reader import (
    TwseFeatureArtifactReader,
)
from src.features.tpex_price_volume_schema import (
    TPEX_PRICE_VOLUME_FEATURE_NAMES,
    TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
    TPEX_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
    TPEX_PRICE_VOLUME_PRICE_BASIS,
)


SOURCE_SNAPSHOT = "1" * 64
IDENTITY_SNAPSHOT = "2" * 64
DATASET_SNAPSHOT = dataset_snapshot_hash(
    source_archive_snapshot_sha256=SOURCE_SNAPSHOT,
    current_identity_snapshot_sha256=IDENTITY_SNAPSHOT,
)


def _feature_row(
    *,
    market: str = "TPEX",
    asset_type: str = "COMMON_STOCK",
    dataset_snapshot: str = DATASET_SNAPSHOT,
) -> dict[str, object]:
    row: dict[str, object] = {
        "dataset_snapshot_sha256": dataset_snapshot,
        "source_archive_snapshot_sha256": SOURCE_SNAPSHOT,
        "current_identity_snapshot_sha256": IDENTITY_SNAPSHOT,
        "archive_id": 6488,
        "source_object_key": "historical/finmind/daily_bars/TPEX/6488.parquet",
        "source_payload_sha256": "3" * 64,
        "source_parquet_sha256": "4" * 64,
        "security_id": 6488,
        "listing_period_id": "CURRENT:TPEX:6488:2011-09-23:OPEN",
        "symbol": "6488",
        "market": market,
        "asset_type": asset_type,
        "listing_date": date(2011, 9, 23),
        "decision_date": date(2026, 7, 17),
        "decision_at": datetime(
            2026,
            7,
            17,
            17,
            tzinfo=ZoneInfo("Asia/Taipei"),
        ),
        "horizon": 5,
        "decision_time_policy_version": "tpex-post-close-1700-asia-taipei-v1",
        "feature_schema_version": TPEX_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
        "feature_schema_hash": TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
        "price_basis": TPEX_PRICE_VOLUME_PRICE_BASIS,
        "availability_mode": "RESEARCH_SCHEDULING_HINT",
        "decision_close_price": 392.5,
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
            name: float(index + 1)
            for index, name in enumerate(TPEX_PRICE_VOLUME_FEATURE_NAMES)
        }
    )
    return row


def _write_artifact(
    path: Path,
    *,
    row: dict[str, object] | None = None,
    dataset_snapshot: str = DATASET_SNAPSHOT,
) -> None:
    writer = TpexArchiveFeatureParquetWriter(
        path,
        dataset_snapshot_sha256=dataset_snapshot,
        source_archive_snapshot_sha256=SOURCE_SNAPSHOT,
        current_identity_snapshot_sha256=IDENTITY_SNAPSHOT,
    )
    writer.write_rows([row or _feature_row(dataset_snapshot=dataset_snapshot)])
    writer.finish()


def test_tpex_manifest_is_typed_and_verified_from_read_back(tmp_path: Path) -> None:
    output = tmp_path / "tpex-features.parquet"
    _write_artifact(output)
    reader = TpexFeatureArtifactReader()

    manifest = reader.manifest_from_parquet(output)
    verified = reader.verify(output, manifest)
    table = reader.read_table(verified)

    assert isinstance(manifest, TpexFeatureArtifactManifest)
    assert isinstance(verified, VerifiedTpexFeatureArtifact)
    assert manifest.manifest_version == TPEX_FEATURE_ARTIFACT_MANIFEST_VERSION
    assert manifest.dataset_version == "tpex-archive-price-volume-5d-v2"
    assert manifest.dataset_snapshot_sha256 == DATASET_SNAPSHOT
    assert manifest.parquet_sha256 == sha256(output.read_bytes()).hexdigest()
    assert manifest.row_count == table.num_rows == 1
    assert verified.point_in_time_verified is False
    assert TpexFeatureArtifactManifest.from_mapping(manifest.to_dict()) == manifest


@pytest.mark.parametrize(
    ("field", "value"),
    [("market", "TWSE"), ("asset_type", "ETF")],
)
def test_tpex_row_scope_tampering_is_rejected(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    output = tmp_path / f"bad-{field}.parquet"
    _write_artifact(output, row={**_feature_row(), field: value})

    with pytest.raises(TpexFeatureArtifactReadError) as captured:
        _ = TpexFeatureArtifactReader().manifest_from_parquet(output)

    assert captured.value.reason_code == "TPEX_FEATURE_ARTIFACT_ROW_CONTRACT_MISMATCH"


def test_tpex_metadata_and_dataset_snapshot_tampering_are_rejected(
    tmp_path: Path,
) -> None:
    metadata_output = tmp_path / "bad-metadata.parquet"
    _write_artifact(metadata_output)
    table = pq.read_table(metadata_output)
    metadata = dict(table.schema.metadata or {})
    metadata[b"feature.schema_hash"] = ("f" * 64).encode("ascii")
    pq.write_table(table.replace_schema_metadata(metadata), metadata_output)

    with pytest.raises(TpexFeatureArtifactReadError) as metadata_error:
        _ = TpexFeatureArtifactReader().manifest_from_parquet(metadata_output)
    assert metadata_error.value.reason_code == "TPEX_FEATURE_ARTIFACT_METADATA_INVALID"

    snapshot_output = tmp_path / "bad-snapshot.parquet"
    _write_artifact(snapshot_output, dataset_snapshot="5" * 64)
    with pytest.raises(TpexFeatureArtifactReadError) as snapshot_error:
        _ = TpexFeatureArtifactReader().manifest_from_parquet(snapshot_output)
    assert (
        snapshot_error.value.reason_code
        == "TPEX_FEATURE_ARTIFACT_INPUT_SNAPSHOT_MISMATCH"
    )


def test_tpex_manifest_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    output = tmp_path / "tpex-features.parquet"
    _write_artifact(output)
    reader = TpexFeatureArtifactReader()
    manifest = reader.manifest_from_parquet(output)

    with pytest.raises(TpexFeatureArtifactReadError) as captured:
        _ = reader.verify(output, replace(manifest, parquet_sha256="6" * 64))

    assert captured.value.reason_code == "TPEX_FEATURE_ARTIFACT_MANIFEST_MISMATCH"


def test_twse_reader_cannot_accept_tpex_artifact(tmp_path: Path) -> None:
    output = tmp_path / "tpex-features.parquet"
    _write_artifact(output)

    with pytest.raises(TwseFeatureArtifactReadError) as captured:
        _ = TwseFeatureArtifactReader().manifest_from_parquet(output)

    assert captured.value.reason_code == "TWSE_FEATURE_ARTIFACT_METADATA_INVALID"


def test_verified_tpex_artifact_cannot_be_forged(tmp_path: Path) -> None:
    output = tmp_path / "tpex-features.parquet"
    _write_artifact(output)
    manifest = TpexFeatureArtifactReader().manifest_from_parquet(output)

    with pytest.raises(TypeError):
        _ = VerifiedTpexFeatureArtifact(
            path=output,
            manifest=manifest,
            _proof=object(),
        )
