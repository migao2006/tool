from __future__ import annotations

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false

from datetime import date, datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, final
from zoneinfo import ZoneInfo

import pytest

from src.config.loader import load_mvp_config
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
from src.pipeline.twse_latest_feature_repository import (
    LatestTwseFeatureRepository,
    LatestTwseFeatureSourceError,
)
from src.pipeline.twse_research_daily_inference import TwseDailyResearchInference
from src.pipeline.twse_research_loaded_bundle import (
    CalibratedDirectionPrediction,
    CalibratedQuantilePrediction,
)
from src.pipeline.twse_research_model_bundle_contracts import (
    BUNDLE_FILE_NAMES,
    BundleFileRecord,
    TwseResearchModelBundleManifest,
)


SOURCE_SNAPSHOT = "a" * 64
IDENTITY_SNAPSHOT = "b" * 64
DATASET_SNAPSHOT = dataset_snapshot_hash(
    source_archive_snapshot_sha256=SOURCE_SNAPSHOT,
    current_identity_snapshot_sha256=IDENTITY_SNAPSHOT,
)
DEFAULT_ROW_DATE = date(2026, 7, 17)


def _row(
    symbol: str,
    *,
    row_date: date = DEFAULT_ROW_DATE,
    available_hour_utc: int = 8,
    close: float = 100.0,
) -> dict[str, object]:
    values: dict[str, object] = {
        "dataset_snapshot_sha256": DATASET_SNAPSHOT,
        "source_archive_snapshot_sha256": SOURCE_SNAPSHOT,
        "current_identity_snapshot_sha256": IDENTITY_SNAPSHOT,
        "archive_id": int(symbol),
        "source_object_key": f"historical/finmind/daily_bars/TWSE/{symbol}.parquet",
        "source_payload_sha256": "c" * 64,
        "source_parquet_sha256": "d" * 64,
        "security_id": int(symbol),
        "listing_period_id": f"CURRENT:TWSE:{symbol}:2000-01-01:OPEN",
        "symbol": symbol,
        "market": "TWSE",
        "asset_type": "COMMON_STOCK",
        "listing_date": date(2000, 1, 1),
        "decision_date": row_date,
        "decision_at": datetime.combine(
            row_date,
            datetime.min.time().replace(hour=17),
            tzinfo=ZoneInfo("Asia/Taipei"),
        ),
        "horizon": 5,
        "decision_time_policy_version": "twse-post-close-1700-asia-taipei-v1",
        "feature_schema_version": TWSE_PRICE_VOLUME_FEATURE_SCHEMA_VERSION,
        "feature_schema_hash": TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
        "price_basis": TWSE_PRICE_VOLUME_PRICE_BASIS,
        "availability_mode": "RESEARCH_SCHEDULING_HINT",
        "decision_close_price": close,
        "latest_available_at": datetime(
            row_date.year,
            row_date.month,
            row_date.day,
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
            for name in TWSE_PRICE_VOLUME_FEATURE_NAMES
        }
    )
    return values


def _artifact(tmp_path: Path, rows: list[dict[str, object]]) -> tuple[Path, Path]:
    output = tmp_path / "twse-research-features.parquet"
    writer = TwseArchiveFeatureParquetWriter(
        output,
        dataset_snapshot_sha256=DATASET_SNAPSHOT,
        source_archive_snapshot_sha256=SOURCE_SNAPSHOT,
        current_identity_snapshot_sha256=IDENTITY_SNAPSHOT,
    )
    writer.write_rows(rows)
    writer.finish()
    manifest = TwseFeatureArtifactReader().manifest_from_parquet(output)
    audit = tmp_path / "twse-research-features-audit.json"
    _ = audit.write_text(
        json.dumps(
            {
                "output_file": output.name,
                "feature_artifact_manifest": manifest.to_dict(),
            }
        ),
        encoding="utf-8",
    )
    return output, audit


def _manifest() -> TwseResearchModelBundleManifest:
    return TwseResearchModelBundleManifest(
        model_version="twse-price-research-h5-v1",
        horizon=5,
        fold_number=4,
        feature_schema_hash=TWSE_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
        input_artifact_sha256="e" * 64,
        dataset_snapshot_id="f" * 64,
        source_hash="8" * 64,
        label_version="twse-five-session-executable-return-v1",
        benchmark_id="TAIEX",
        benchmark_version="official-price-index-ohlc-v1",
        cost_profile_version="tw_stock_swing_v1:base_cost",
        random_seed=20260718,
        feature_names=TWSE_PRICE_VOLUME_FEATURE_NAMES,
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
class _FakeBundle:
    def __init__(self) -> None:
        self.manifest: TwseResearchModelBundleManifest = _manifest()
        self.probability_calibrator: SimpleNamespace = SimpleNamespace(
            version="prob-v1"
        )
        self.interval_calibrator: SimpleNamespace = SimpleNamespace(
            version="interval-v1"
        )

    def transform(self, frame: Any, decision_dates: list[date]) -> Any:
        assert tuple(frame.columns) == TWSE_PRICE_VOLUME_FEATURE_NAMES
        assert len(decision_dates) == len(frame)
        return frame

    @staticmethod
    def predict_rank(matrix: Any) -> tuple[float, ...]:
        return tuple(0.9 if index else 0.1 for index in range(len(matrix)))

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


def test_latest_feature_is_scored_without_labels_and_costs_are_recomputed(
    tmp_path: Path,
) -> None:
    parquet, audit = _artifact(
        tmp_path,
        [
            _row("2330", row_date=date(2026, 7, 16)),
            _row("2330"),
            _row("2317", close=150.0),
        ],
    )
    cross_section = LatestTwseFeatureRepository().load(parquet, audit)

    snapshot = TwseDailyResearchInference().run(
        cross_section,
        _FakeBundle(),  # pyright: ignore[reportArgumentType]
        load_mvp_config(),
    )

    assert snapshot.as_of_date == date(2026, 7, 17)
    assert [row.symbol for row in snapshot.predictions] == ["2317", "2330"]
    assert {row.evaluation_scope for row in snapshot.predictions} == {
        "RETROSPECTIVE_RESEARCH_INFERENCE"
    }
    assert all(row.data_quality_status == "WARN" for row in snapshot.predictions)
    assert all(row.estimated_round_trip_cost > 0 for row in snapshot.predictions)
    for row in snapshot.predictions:
        assert len(row.gates) == 8
        assert row.to_dict()["decision"] == "NO_TRADE"
        assert "RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY" not in row.reason_codes
        gates = {gate.gate: gate for gate in row.gates}
        assert gates["tradability_gate"].reason_code == (
            "FORMAL_TRADABILITY_INPUT_MISSING"
        )
        assert gates["market_exposure_cap"].source_date is None
        assert gates["position_capacity_limits"].source_date is None
        assert row.net_q50 == pytest.approx(
            row.gross_q50 - row.estimated_round_trip_cost
        )
        assert sum(
            (row.calibrated_p_up, row.calibrated_p_neutral, row.calibrated_p_down)
        ) == pytest.approx(1.0)
    assert snapshot.validation["research_decision_policy_executed"] is True
    assert snapshot.validation["formal_decision_policy_executed"] is False


def test_latest_feature_rejects_values_available_after_decision(
    tmp_path: Path,
) -> None:
    parquet, audit = _artifact(
        tmp_path,
        [_row("2330", available_hour_utc=12)],
    )

    with pytest.raises(LatestTwseFeatureSourceError) as captured:
        _ = LatestTwseFeatureRepository().load(parquet, audit)

    assert captured.value.reason_code == "TWSE_FEATURE_POINT_IN_TIME_VIOLATION"
