from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.config.loader import load_mvp_config
from src.core.research_prediction_contract import (
    TPEX_RESEARCH_PREDICTION_CONTRACT_VERSION,
)
from src.features.tpex_price_volume_schema import (
    TPEX_PRICE_VOLUME_FEATURE_NAMES,
    TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
)
from src.pipeline.contracts import (
    PipelineBatch,
    PipelineContext,
    PipelineMode,
    PipelineStatus,
)
from src.pipeline.tpex_research_runner import TpexPriceResearchRunner
from src.pipeline.research_run_provenance import (
    ResearchRunProvenanceError,
    research_run_provenance,
)
from src.pipeline.twse_prepared_research_contracts import (
    PreparedResearchArtifactManifest,
    prepared_dataset_snapshot_hash_for_market,
)
from src.pipeline.twse_research_evaluation_contracts import (
    DirectionEvaluation,
    QuantileEvaluation,
    RankEvaluation,
)
from src.pipeline.twse_research_prediction_publisher import (
    TwseResearchPredictionPublisher,
    build_fold_research_predictions,
)


UTC = timezone.utc


def _prepared_source_metadata() -> dict[str, object]:
    feature_artifact = "1" * 64
    daily_snapshot = "2" * 64
    identity_snapshot = "3" * 64
    benchmark_snapshot = "4" * 64
    calendar_snapshot = "5" * 64
    feature_dataset_snapshot = "6" * 64
    label_version = "tpex-research-unadjusted-open-close-5d-v1"
    cost_profile_version = "tw_stock_swing_v1:base_cost"
    prepared_snapshot = prepared_dataset_snapshot_hash_for_market(
        market="TPEX",
        feature_artifact_sha256=feature_artifact,
        daily_archive_snapshot_sha256=daily_snapshot,
        current_identity_snapshot_sha256=identity_snapshot,
        benchmark_archive_snapshot_sha256=benchmark_snapshot,
        calendar_snapshot_sha256=calendar_snapshot,
        feature_dataset_snapshot_id=feature_dataset_snapshot,
        label_version=label_version,
        cost_profile_version=cost_profile_version,
        horizon=5,
    )
    manifest = PreparedResearchArtifactManifest(
        parquet_sha256="a" * 64,
        schema_sha256="7" * 64,
        byte_size=1,
        row_count=2,
        prepared_dataset_snapshot_sha256=prepared_snapshot,
        dataset_snapshot_id=feature_dataset_snapshot,
        daily_archive_snapshot_sha256=daily_snapshot,
        current_identity_snapshot_sha256=identity_snapshot,
        feature_artifact_sha256=feature_artifact,
        calendar_snapshot_sha256=calendar_snapshot,
        source_hash="8" * 64,
        benchmark_snapshot_sha256=benchmark_snapshot,
        benchmark_id="TPEX_PRICE_INDEX",
        benchmark_version="tpex-price-index-v1",
        feature_schema_hash=TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
        label_version=label_version,
        cost_profile_version=cost_profile_version,
        market="TPEX",
        artifact_version="tpex-prepared-research-5d.v1",
        feature_source_run_id="29716316791",
        feature_source_run_sha="c" * 40,
        feature_source_artifact_id="8450000001",
        feature_source_artifact_digest="sha256:" + "d" * 64,
    )
    return {"prepared_artifact_manifest": manifest.to_dict()}


def _frame(*, market: str = "TPEX") -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for offset, symbol in enumerate(("6488", "5274")):
        decision_at = datetime(2026, 7, 16 + offset, 6, 30, tzinfo=UTC)
        row: dict[str, object] = {
            "symbol": symbol,
            "market": market,
            "horizon": 5,
            "decision_date": decision_at.date(),
            "decision_at": decision_at,
            "available_at": decision_at,
            "source_latest_available_at": decision_at,
            "availability_basis": "SOURCE_AVAILABLE_AT",
            "entry_at": decision_at + timedelta(days=1),
            "exit_at": decision_at + timedelta(days=7),
            "gross_return": 0.03 - offset * 0.02,
            "net_return": 0.024 - offset * 0.02,
            "net_alpha": 0.012 - offset * 0.01,
            "round_trip_cost_rate": 0.006,
            "direction": "UP" if offset == 0 else "NEUTRAL",
            "data_quality_status": "WARN",
            "system_status": "RESEARCH_ONLY",
            "usage_scope": "MODEL_RESEARCH_ONLY",
            "reason_codes": ("TPEX_PRICE_ONLY_RESEARCH",),
            "feature_schema_hash": TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
            "label_version": "tpex-research-unadjusted-open-close-5d-v1",
            "benchmark_id": "TPEX_PRICE_INDEX",
            "benchmark_version": "tpex-price-index-v1",
            "cost_profile_version": "tw_stock_swing_v1:base_cost",
            "dataset_snapshot_id": "d" * 64,
            "source_hash": "a" * 64,
        }
        row.update(
            {name: 0.01 + offset * 0.001 for name in TPEX_PRICE_VOLUME_FEATURE_NAMES}
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _context(tmp_path: Path) -> PipelineContext:
    return PipelineContext(
        mode=PipelineMode.TRAIN,
        horizon=5,
        config=load_mvp_config("config/five_day_mvp.toml"),
        artifact_root=tmp_path,
    )


def test_tpex_runner_accepts_venue_schema_before_history_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    result = TpexPriceResearchRunner().train(
        PipelineBatch(
            records=_frame(),
            source_uri="memory://tpex-research",
            source_hash="a" * 64,
            source_metadata=_prepared_source_metadata(),
        ),
        _context(tmp_path),
    )

    assert result.status is PipelineStatus.RESEARCH_ONLY
    assert result.reason_codes == ("INSUFFICIENT_LOCKED_HOLDOUT_HISTORY",)
    assert result.model_version == "tpex-price-research-h5-v1"
    assert result.feature_schema_hash == TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH


def test_tpex_runner_rejects_twse_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    result = TpexPriceResearchRunner().train(
        PipelineBatch(
            records=_frame(market="TWSE"),
            source_uri="memory://wrong-market",
            source_hash="a" * 64,
            source_metadata=_prepared_source_metadata(),
        ),
        _context(tmp_path),
    )

    assert result.reason_codes == ("TPEX_RESEARCH_DATASET_INVALID",)


def test_tpex_runner_requires_full_prepared_provenance(tmp_path: Path) -> None:
    result = TpexPriceResearchRunner().train(
        PipelineBatch(
            records=_frame(),
            source_uri="memory://missing-prepared-provenance",
            source_hash="a" * 64,
        ),
        _context(tmp_path),
    )

    assert result.reason_codes == ("PREPARED_ARTIFACT_PROVENANCE_MISSING",)


def test_tpex_runner_rejects_prepared_artifact_without_feature_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    metadata = _prepared_source_metadata()
    raw_manifest = metadata["prepared_artifact_manifest"]
    assert isinstance(raw_manifest, dict)
    manifest = raw_manifest.copy()
    for name in (
        "feature_source_run_id",
        "feature_source_run_sha",
        "feature_source_artifact_id",
        "feature_source_artifact_digest",
    ):
        manifest[name] = None
    result = TpexPriceResearchRunner().train(
        PipelineBatch(
            records=_frame(),
            source_uri="memory://missing-feature-source",
            source_hash="a" * 64,
            source_metadata={"prepared_artifact_manifest": manifest},
        ),
        _context(tmp_path),
    )

    assert result.reason_codes == ("PREPARED_FEATURE_SOURCE_PROVENANCE_MISSING",)


def test_tpex_runner_rejects_feature_source_without_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    metadata = _prepared_source_metadata()
    raw_manifest = metadata["prepared_artifact_manifest"]
    assert isinstance(raw_manifest, dict)
    manifest = raw_manifest.copy()
    manifest["feature_source_artifact_digest"] = None
    result = TpexPriceResearchRunner().train(
        PipelineBatch(
            records=_frame(),
            source_uri="memory://missing-feature-digest",
            source_hash="a" * 64,
            source_metadata={"prepared_artifact_manifest": manifest},
        ),
        _context(tmp_path),
    )

    assert result.reason_codes == ("PREPARED_FEATURE_SOURCE_PROVENANCE_MISSING",)


def test_github_run_requires_verified_source_run_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)
    monkeypatch.delenv("TPEX_PREPARED_SOURCE_RUN_ID", raising=False)
    monkeypatch.delenv("TPEX_PREPARED_SOURCE_RUN_SHA", raising=False)
    batch = PipelineBatch(
        records=_frame(),
        source_uri="memory://github-provenance",
        source_hash="a" * 64,
        source_metadata=_prepared_source_metadata(),
    )

    with pytest.raises(ResearchRunProvenanceError) as error:
        research_run_provenance(batch, expected_market="TPEX")

    assert error.value.reason_code == "PREPARED_SOURCE_RUN_PROVENANCE_MISSING"


def test_github_run_retains_all_prepared_snapshot_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)
    monkeypatch.setenv("TPEX_PREPARED_SOURCE_RUN_ID", "29722499185")
    monkeypatch.setenv("TPEX_PREPARED_SOURCE_RUN_SHA", "e" * 40)
    batch = PipelineBatch(
        records=_frame(),
        source_uri="memory://github-provenance",
        source_hash="a" * 64,
        source_metadata=_prepared_source_metadata(),
    )

    provenance = research_run_provenance(batch, expected_market="TPEX").to_dict()
    manifest = provenance["prepared_artifact_manifest"]

    assert isinstance(manifest, dict)
    assert provenance["git_commit"] == "f" * 40
    assert provenance["git_commit_source"] == "GITHUB_SHA"
    assert provenance["source_prepared_run_id"] == "29722499185"
    assert provenance["source_prepared_run_sha"] == "e" * 40
    assert provenance["source_feature_run_id"] == "29716316791"
    assert provenance["source_feature_run_sha"] == "c" * 40
    assert provenance["source_feature_artifact_id"] == "8450000001"
    assert provenance["source_feature_artifact_digest"] == "sha256:" + "d" * 64
    for field_name in (
        "prepared_dataset_snapshot_sha256",
        "daily_archive_snapshot_sha256",
        "current_identity_snapshot_sha256",
        "calendar_snapshot_sha256",
        "benchmark_snapshot_sha256",
        "feature_artifact_sha256",
    ):
        assert isinstance(manifest[field_name], str)
        assert len(manifest[field_name]) == 64


def test_fold_prediction_preserves_tpex_market() -> None:
    frame = _frame()
    batch = build_fold_research_predictions(
        frame=frame,
        train_indices=(0,),
        test_indices=(1,),
        fold_number=1,
        rank=RankEvaluation(metrics={}, model_scores=(0.8,)),
        direction=DirectionEvaluation(
            metrics={},
            probabilities=((0.6, 0.3, 0.1),),
            calibration_version="probability-calibration-v1",
        ),
        quantiles=QuantileEvaluation(
            metrics={},
            gross_quantiles=((-0.02, 0.01, 0.05),),
            net_quantiles=((-0.026, 0.004, 0.044),),
            raw_crossed=(False,),
            calibration_version="interval-calibration-v1",
        ),
    )

    assert batch.training_end_date == date(2026, 7, 16)
    assert batch.predictions[0].market == "TPEX"
    assert batch.predictions[0].symbol == "5274"


def test_tpex_prediction_uses_independent_snapshot_contract(tmp_path: Path) -> None:
    frame = _frame()
    batch = build_fold_research_predictions(
        frame=frame,
        train_indices=(0,),
        test_indices=(1,),
        fold_number=1,
        rank=RankEvaluation(metrics={}, model_scores=(0.8,)),
        direction=DirectionEvaluation(
            metrics={},
            probabilities=((0.6, 0.3, 0.1),),
            calibration_version="probability-calibration-v1",
        ),
        quantiles=QuantileEvaluation(
            metrics={},
            gross_quantiles=((-0.02, 0.01, 0.05),),
            net_quantiles=((-0.026, 0.004, 0.044),),
            raw_crossed=(False,),
            calibration_version="interval-calibration-v1",
        ),
    )
    published = TwseResearchPredictionPublisher().publish(
        tmp_path / "tpex.json",
        fold_batches=(batch,),
        horizon=5,
        model_version="tpex-price-research-h5-v1",
        feature_schema_hash=TPEX_PRICE_VOLUME_FEATURE_SCHEMA_HASH,
        input_artifact_sha256="a" * 64,
        provenance={
            "dataset_snapshot_id": "d" * 64,
            "source_hash": "b" * 64,
            "label_version": "tpex-research-unadjusted-open-close-5d-v1",
            "benchmark_id": "TPEX_PRICE_INDEX",
            "benchmark_version": "tpex-price-index-v1",
            "cost_profile_version": "tw_stock_swing_v1:base_cost",
        },
        model_metadata={"rank_model": "LightGBM"},
        cost_metadata={"cost_profile": "base_cost"},
        validation={"fold_count": 1, "locked_holdout_executed": False},
        reason_codes=("TPEX_PRICE_ONLY_RESEARCH",),
    )

    payload = published.snapshot.to_dict()
    assert payload["market"] == "TPEX"
    assert payload["artifact_contract_version"] == (
        TPEX_RESEARCH_PREDICTION_CONTRACT_VERSION
    )
