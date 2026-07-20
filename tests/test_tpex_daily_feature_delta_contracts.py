from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest

from src.data.research.tpex_daily_feature_delta_contracts import (
    TPEX_DAILY_FEATURE_DELTA_MANIFEST_VERSION,
    TPEX_DAILY_FEATURE_DELTA_REASONS,
    TPEX_DAILY_FEATURE_DELTA_VERSION,
    TpexDailyFeatureDeltaAudit,
    TpexDailyFeatureDeltaError,
    TpexDailyFeatureDeltaManifest,
    daily_feature_delta_snapshot_hash,
)
from src.features.tpex_price_volume_schema import (
    TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
    TPEX_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
)


AS_OF_DATE = date(2026, 7, 20)
SOURCE_ARCHIVE_SNAPSHOT = "1" * 64
CURRENT_IDENTITY_SNAPSHOT = "2" * 64
DAILY_BAR_SNAPSHOT = "3" * 64


def _dataset_snapshot(
    *,
    source_archive_snapshot: str = SOURCE_ARCHIVE_SNAPSHOT,
    current_identity_snapshot: str = CURRENT_IDENTITY_SNAPSHOT,
    daily_bar_snapshot: str = DAILY_BAR_SNAPSHOT,
    as_of_date: date = AS_OF_DATE,
) -> str:
    return daily_feature_delta_snapshot_hash(
        source_archive_snapshot_sha256=source_archive_snapshot,
        current_identity_snapshot_sha256=current_identity_snapshot,
        daily_bar_snapshot_sha256=daily_bar_snapshot,
        as_of_date=as_of_date,
    )


def _manifest(**overrides: object) -> TpexDailyFeatureDeltaManifest:
    values: dict[str, object] = {
        "parquet_sha256": "4" * 64,
        "parquet_schema_sha256": "5" * 64,
        "byte_size": 1_024,
        "row_count": 2,
        "dataset_snapshot_sha256": _dataset_snapshot(),
        "source_archive_snapshot_sha256": SOURCE_ARCHIVE_SNAPSHOT,
        "current_identity_snapshot_sha256": CURRENT_IDENTITY_SNAPSHOT,
        "daily_bar_snapshot_sha256": DAILY_BAR_SNAPSHOT,
        "as_of_date": AS_OF_DATE,
    }
    values.update(overrides)
    return TpexDailyFeatureDeltaManifest(**values)


def test_delta_snapshot_hash_is_deterministic_and_binds_every_input() -> None:
    original = _dataset_snapshot()

    assert original == _dataset_snapshot()
    assert original != _dataset_snapshot(source_archive_snapshot="a" * 64)
    assert original != _dataset_snapshot(current_identity_snapshot="b" * 64)
    assert original != _dataset_snapshot(daily_bar_snapshot="c" * 64)
    assert original != _dataset_snapshot(as_of_date=date(2026, 7, 21))


def test_manifest_round_trip_preserves_the_frozen_research_scope() -> None:
    manifest = _manifest()
    mapping = manifest.to_dict()
    mapping["parquet_sha256"] = str(mapping["parquet_sha256"]).upper()

    restored = TpexDailyFeatureDeltaManifest.from_mapping(mapping)

    assert restored == manifest
    assert restored.manifest_version == TPEX_DAILY_FEATURE_DELTA_MANIFEST_VERSION
    assert restored.dataset_version == TPEX_DAILY_FEATURE_DELTA_VERSION
    assert restored.feature_schema_version == TPEX_PRICE_VOLUME_FEATURE_SCHEMA_VERSION
    assert restored.feature_schema_hash == TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH
    assert restored.horizon == 5
    assert restored.system_status == "RESEARCH_ONLY"
    assert restored.point_in_time_status == "UNVERIFIED"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dataset_snapshot_sha256", "f" * 64),
        ("daily_bar_snapshot_sha256", "not-a-sha256"),
        ("as_of_date", "2026-07-21"),
        ("horizon", 10),
        ("availability_mode", "OFFICIAL_PUBLICATION_AT"),
        ("system_status", "PASS"),
        ("row_count", 0),
    ],
)
def test_manifest_tampering_fails_closed(field: str, value: object) -> None:
    mapping = _manifest().to_dict()
    mapping[field] = value

    with pytest.raises(TpexDailyFeatureDeltaError) as captured:
        TpexDailyFeatureDeltaManifest.from_mapping(mapping)

    assert captured.value.reason_code == "TPEX_DAILY_FEATURE_DELTA_MANIFEST_INVALID"


def test_manifest_missing_required_provenance_fails_closed() -> None:
    mapping = _manifest().to_dict()
    del mapping["source_archive_snapshot_sha256"]

    with pytest.raises(TpexDailyFeatureDeltaError) as captured:
        TpexDailyFeatureDeltaManifest.from_mapping(mapping)

    assert captured.value.reason_code == "TPEX_DAILY_FEATURE_DELTA_MANIFEST_INVALID"


def test_direct_manifest_snapshot_tampering_cannot_create_a_valid_contract() -> None:
    manifest = _manifest()

    with pytest.raises(ValueError, match="do not reproduce its ID"):
        replace(manifest, daily_bar_snapshot_sha256="6" * 64)
    with pytest.raises(ValueError, match="frozen research-only scope"):
        replace(manifest, usage_scope="MODEL_TRAINING")


def test_delta_audit_exposes_fixed_limitations_and_rejects_partial_verification() -> (
    None
):
    audit = TpexDailyFeatureDeltaAudit(
        generated_at=datetime(2026, 7, 20, 12, tzinfo=timezone.utc),
        as_of_date=AS_OF_DATE,
        dataset_snapshot_sha256=_dataset_snapshot(),
        source_archive_snapshot_sha256=SOURCE_ARCHIVE_SNAPSHOT,
        current_identity_snapshot_sha256=CURRENT_IDENTITY_SNAPSHOT,
        daily_bar_snapshot_sha256=DAILY_BAR_SNAPSHOT,
        manifest_count=3,
        daily_source_row_count=889,
        verified_archive_count=3,
        output_row_count=876,
        excluded_row_count=13,
        exclusion_reason_counts={"MISSING_OHLC": 13},
    )

    payload = audit.as_json()
    assert payload["as_of_date"] == AS_OF_DATE.isoformat()
    assert payload["output_row_count"] == 876
    assert payload["reason_codes"] == list(TPEX_DAILY_FEATURE_DELTA_REASONS)
    assert payload["usage_scope"] == "FEATURE_RESEARCH_ONLY"
    assert payload["system_status"] == "RESEARCH_ONLY"

    with pytest.raises(ValueError, match="every archive must be verified"):
        replace(audit, verified_archive_count=2)
