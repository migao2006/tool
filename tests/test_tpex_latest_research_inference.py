from __future__ import annotations

# pyright: reportAny=false, reportExplicitAny=false

from datetime import date, datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, final
from zoneinfo import ZoneInfo

import pytest

from src.config.loader import load_mvp_config
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
from src.pipeline.tpex_latest_feature_repository import (
    LatestTpexFeatureRepository,
    LatestTpexFeatureSourceError,
)
from src.pipeline.tpex_research_daily_inference import TpexDailyResearchInference
from src.pipeline.twse_research_loaded_bundle import (
    CalibratedDirectionPrediction,
    CalibratedQuantilePrediction,
)
from src.pipeline.twse_research_model_bundle_contracts import (
    BUNDLE_FILE_NAMES,
    TPEX_RESEARCH_BUNDLE_CONTRACT_VERSION,
    BundleFileRecord,
    TwseResearchModelBundleManifest,
)


SOURCE_SNAPSHOT = "a" * 64
IDENTITY_SNAPSHOT = "b" * 64
DATASET_SNAPSHOT = dataset_snapshot_hash(
    source_archive_snapshot_sha256=SOURCE_SNAPSHOT,
    current_identity_snapshot_sha256=IDENTITY_SNAPSHOT,
)
ROW_DATE = date(2026, 7, 17)


def _row(symbol: str, *, available_hour_utc: int = 8) -> dict[str, object]:
    values: dict[str, object] = {
        "dataset_snapshot_sha256": DATASET_SNAPSHOT,
        "source_archive_snapshot_sha256": SOURCE_SNAPSHOT,
        "current_identity_snapshot_sha256": IDENTITY_SNAPSHOT,
        "archive_id": int(symbol),
        "source_object_key": f"historical/finmind/daily_bars/TPEX/{symbol}.parquet",
        "source_payload_sha256": "c" * 64,
        "source_parquet_sha256": "d" * 64,
        "security_id": int(symbol),
        "listing_period_id": f"CURRENT:TPEX:{symbol}:2000-01-01:OPEN",
        "symbol": symbol,
        "market": "TPEX",
        "asset_type": "COMMON_STOCK",
        "listing_date": date(2000, 1, 1),
        "decision_date": ROW_DATE,
        "decision_at": datetime.combine(
            ROW_DATE,
            datetime.min.time().replace(hour=17),
            tzinfo=ZoneInfo("Asia/Taipei"),
        ),
        "horizon": 5,
        "decision_time_policy_version": "tpex-post-close-1700-asia-taipei-v1",
        "feature_schema_version": TPEX_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
        "feature_schema_hash": TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
        "price_basis": TPEX_PRICE_VOLUME_PRICE_BASIS,
        "availability_mode": "RESEARCH_SCHEDULING_HINT",
        "decision_close_price": 100.0,
        "latest_available_at": datetime(
            ROW_DATE.year,
            ROW_DATE.month,
            ROW_DATE.day,
            available_hour_utc,
            tzinfo=timezone.utc,
        ),
        "latest_observed_available_at": datetime(2026, 7, 19, 4, tzinfo=timezone.utc),
        "point_in_time_audit_pass": False,
        "hard_fail": False,
        "research_limitation_reason_codes": ["RESEARCH_SCHEDULING_HINT"],
        "hard_fail_reason_codes": [],
        "label_status": "LABELS_NOT_ASSEMBLED",
        "usage_scope": "FEATURE_RESEARCH_ONLY",
        "system_status": "RESEARCH_ONLY",
        "reason_codes": json.dumps(["POINT_IN_TIME_UNVERIFIED"]),
        "source_reason_codes": json.dumps(["POINT_IN_TIME_UNVERIFIED"]),
    }
    values.update(
        {
            name: (20_000_000.0 if name == "adv20_ntd" else 0.01)
            for name in TPEX_PRICE_VOLUME_FEATURE_NAMES
        }
    )
    return values


def _artifact(tmp_path: Path, rows: list[dict[str, object]]) -> tuple[Path, Path]:
    output = tmp_path / "tpex-research-features.parquet"
    writer = TpexArchiveFeatureParquetWriter(
        output,
        dataset_snapshot_sha256=DATASET_SNAPSHOT,
        source_archive_snapshot_sha256=SOURCE_SNAPSHOT,
        current_identity_snapshot_sha256=IDENTITY_SNAPSHOT,
    )
    writer.write_rows(rows)
    writer.finish()
    manifest = TpexFeatureArtifactReader().manifest_from_parquet(output)
    audit = tmp_path / "tpex-research-features-audit.json"
    _ = audit.write_text(
        json.dumps(
            {"output_file": output.name, "feature_artifact_manifest": manifest.to_dict()}
        ),
        encoding="utf-8",
    )
    return output, audit


def _manifest() -> TwseResearchModelBundleManifest:
    return TwseResearchModelBundleManifest(
        model_version="tpex-price-research-h5-v1",
        market="TPEX",
        contract_version=TPEX_RESEARCH_BUNDLE_CONTRACT_VERSION,
        horizon=5,
        fold_number=4,
        feature_schema_hash=TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
        input_artifact_sha256="e" * 64,
        dataset_snapshot_id="f" * 64,
        source_hash="8" * 64,
        label_version="tpex-research-unadjusted-open-close-5d-v1",
        benchmark_id="TPEX_PRICE_INDEX",
        benchmark_version="official-price-index-ohlc-v1",
        cost_profile_version="tw_stock_swing_v1:base_cost",
        random_seed=20260718,
        feature_names=TPEX_PRICE_VOLUME_FEATURE_NAMES,
        direction_classes=("DOWN", "NEUTRAL", "UP"),
        training_start_date=date(2018, 4, 9),
        training_end_date=date(2024, 6, 18),
        calibration_start_date=date(2024, 7, 3),
        calibration_end_date=date(2025, 1, 6),
        evaluated_test_start_date=date(2025, 1, 21),
        evaluated_test_end_date=date(2025, 5, 2),
        created_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
        files={
            name: BundleFileRecord(relative_path=path, sha256="9" * 64, byte_size=1)
            for name, path in BUNDLE_FILE_NAMES.items()
        },
        library_versions={"lightgbm": "4.6.0"},
        reason_codes=("MODEL_NOT_FORMALLY_PROMOTED",),
    )


@final
class _FakeTpexBundle:
    def __init__(self) -> None:
        self.manifest = _manifest()
        self.probability_calibrator = SimpleNamespace(version="prob-v1")
        self.interval_calibrator = SimpleNamespace(version="interval-v1")

    def transform(self, frame: Any, decision_dates: list[date]) -> Any:
        assert tuple(frame.columns) == TPEX_PRICE_VOLUME_FEATURE_NAMES
        assert len(decision_dates) == len(frame)
        return frame

    @staticmethod
    def predict_rank(matrix: Any) -> tuple[float, ...]:
        return tuple(float(index) for index in range(len(matrix)))

    @staticmethod
    def predict_direction(matrix: Any) -> tuple[CalibratedDirectionPrediction, ...]:
        return tuple(
            CalibratedDirectionPrediction(0.6, 0.3, 0.1) for _ in range(len(matrix))
        )

    @staticmethod
    def predict_quantiles(matrix: Any) -> tuple[CalibratedQuantilePrediction, ...]:
        return tuple(
            CalibratedQuantilePrediction(-0.02, 0.01, 0.05, False)
            for _ in range(len(matrix))
        )


def test_tpex_latest_feature_scores_only_tpex_and_emits_tpex_contract(
    tmp_path: Path,
) -> None:
    parquet, audit = _artifact(tmp_path, [_row("6488"), _row("8299")])
    cross_section = LatestTpexFeatureRepository().load(parquet, audit)

    snapshot = TpexDailyResearchInference().run(
        cross_section,
        _FakeTpexBundle(),  # pyright: ignore[reportArgumentType]
        load_mvp_config(),
    )

    assert snapshot.market == "TPEX"
    assert snapshot.artifact_contract_version == (
        "tpex-research-prediction-snapshot.v1"
    )
    assert {row.market for row in snapshot.predictions} == {"TPEX"}
    assert all(row.to_dict()["decision"] == "NO_TRADE" for row in snapshot.predictions)
    assert "TPEX_PRICE_ONLY_RESEARCH" in snapshot.reason_codes
    assert snapshot.validation["locked_holdout_executed"] is False


def test_tpex_latest_feature_rejects_values_available_after_decision(
    tmp_path: Path,
) -> None:
    parquet, audit = _artifact(tmp_path, [_row("6488", available_hour_utc=12)])

    with pytest.raises(LatestTpexFeatureSourceError) as captured:
        _ = LatestTpexFeatureRepository().load(parquet, audit)

    assert captured.value.reason_code == "TPEX_FEATURE_POINT_IN_TIME_VIOLATION"


def test_tpex_daily_inference_rejects_a_twse_bound_bundle(tmp_path: Path) -> None:
    parquet, audit = _artifact(tmp_path, [_row("6488")])
    cross_section = LatestTpexFeatureRepository().load(parquet, audit)
    wrong_bundle = _FakeTpexBundle()
    object.__setattr__(wrong_bundle.manifest, "market", "TWSE")

    with pytest.raises(ValueError, match="market identity mismatch"):
        _ = TpexDailyResearchInference().run(
            cross_section,
            wrong_bundle,  # pyright: ignore[reportArgumentType]
            load_mvp_config(),
        )
