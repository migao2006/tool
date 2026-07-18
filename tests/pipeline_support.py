from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path

import pandas as pd

from src.pipeline.contracts import (
    PipelineBatch,
    PipelineContext,
    PipelineMode,
    PipelineResult,
    PipelineStatus,
)
from src.pipeline.promotion import (
    PromotionBinding,
    REQUIRED_MODEL_ARTIFACTS,
    REQUIRED_PROMOTION_CHECKS,
    promotion_manifest_path,
)


CONFIG = Path(__file__).parents[1] / "config" / "five_day_mvp.toml"
TEST_RUN_ID = "test-run-20260718"
TEST_MODEL_VERSION = "test-model-v1"
TEST_FEATURE_SCHEMA_HASH = "a" * 64
TEST_COST_PROFILE_VERSION = "test-cost-v1"
TEST_TRAINING_END_DATE = date(2026, 6, 30)


def write_config_with_status(root: Path, status: PipelineStatus) -> Path:
    config = root / "five_day_mvp.toml"
    config.write_text(
        CONFIG.read_text(encoding="utf-8").replace(
            'status = "RESEARCH_ONLY"',
            f'status = "{status.value}"',
            1,
        ),
        encoding="utf-8",
    )
    return config


def write_pass_manifest(
    artifact_root: Path,
    *,
    horizon: int = 5,
    mode: PipelineMode = PipelineMode.TRAIN,
    source_hash: str = "abc123",
    training_end_date: date = TEST_TRAINING_END_DATE,
) -> dict[str, str]:
    target = promotion_manifest_path(
        artifact_root,
        horizon=horizon,
        mode=mode.value,
        run_id=TEST_RUN_ID,
    )
    target.parent.mkdir(parents=True)
    artifact_dir = artifact_root / f"horizon_{horizon}" / "models" / TEST_RUN_ID
    artifact_dir.mkdir(parents=True)
    artifact_uris: dict[str, str] = {}
    artifact_hashes: dict[str, str] = {}
    for name in REQUIRED_MODEL_ARTIFACTS:
        artifact_path = artifact_dir / f"{name}.bin"
        content = f"{TEST_RUN_ID}:{name}".encode()
        artifact_path.write_bytes(content)
        artifact_uris[name] = str(artifact_path)
        artifact_hashes[name] = hashlib.sha256(content).hexdigest()
    target.write_text(
        json.dumps(
            {
                "status": "PASS",
                "horizon": horizon,
                "mode": mode.value,
                "run_id": TEST_RUN_ID,
                "source_hash": source_hash,
                "model_version": TEST_MODEL_VERSION,
                "feature_schema_hash": TEST_FEATURE_SCHEMA_HASH,
                "cost_profile_version": TEST_COST_PROFILE_VERSION,
                "training_end_date": training_end_date.isoformat(),
                "locked_holdout_executed": True,
                "checks": {name: "PASS" for name in REQUIRED_PROMOTION_CHECKS},
                "artifact_uris": artifact_uris,
                "artifact_hashes": artifact_hashes,
            }
        ),
        encoding="utf-8",
    )
    return artifact_uris


def promotion_binding(
    artifact_uris: dict[str, str],
    *,
    mode: PipelineMode = PipelineMode.TRAIN,
    source_hash: str = "abc123",
    training_end_date: date = TEST_TRAINING_END_DATE,
    effective_date: date = date(2026, 7, 18),
) -> PromotionBinding:
    return PromotionBinding(
        horizon=5,
        mode=mode.value,
        run_id=TEST_RUN_ID,
        source_hash=source_hash,
        model_version=TEST_MODEL_VERSION,
        feature_schema_hash=TEST_FEATURE_SCHEMA_HASH,
        cost_profile_version=TEST_COST_PROFILE_VERSION,
        training_end_date=training_end_date,
        effective_date=effective_date,
        artifact_uris=artifact_uris,
    )


def frame(*, late: bool = False) -> pd.DataFrame:
    decision = "2026-07-17T06:00:00Z"
    available = "2026-07-17T07:00:00Z" if late else "2026-07-17T05:59:00Z"
    return pd.DataFrame(
        {
            "symbol": ["2330"],
            "horizon": [5],
            "decision_at": [decision],
            "available_at": [available],
        }
    )


class Repository:
    def __init__(self, records: pd.DataFrame) -> None:
        self.records = records

    def load(
        self,
        *,
        mode: PipelineMode,
        horizon: int,
        as_of_date: date | None,
    ) -> PipelineBatch:
        del mode, horizon, as_of_date
        return PipelineBatch(self.records, "memory://real-test-fixture", "abc123")


class RecordingRunner:
    def __init__(
        self,
        *,
        status: PipelineStatus = PipelineStatus.PASS,
        source_uri: str | None = None,
        source_hash: str | None = None,
        records_read: int | None = None,
        artifacts: dict[str, str] | None = None,
        training_end_date: date = TEST_TRAINING_END_DATE,
    ) -> None:
        self.calls: list[PipelineMode] = []
        self.status = status
        self.source_uri = source_uri
        self.source_hash = source_hash
        self.records_read = records_read
        self.artifacts = artifacts
        self.training_end_date = training_end_date

    def _result(
        self,
        mode: PipelineMode,
        batch: PipelineBatch,
        horizon: int,
    ) -> PipelineResult:
        self.calls.append(mode)
        return PipelineResult(
            mode=mode,
            horizon=horizon,
            status=self.status,
            reason_codes=()
            if self.status is PipelineStatus.PASS
            else ("RUNNER_RESEARCH_RESULT",),
            records_read=self.records_read
            if self.records_read is not None
            else len(batch.records),
            artifacts=self.artifacts
            or {name: f"memory://{name}" for name in REQUIRED_MODEL_ARTIFACTS},
            metrics={"validation_status": "PASS"},
            source_uri=self.source_uri or batch.source_uri,
            source_hash=self.source_hash or batch.source_hash,
            run_id=TEST_RUN_ID,
            model_version=TEST_MODEL_VERSION,
            feature_schema_hash=TEST_FEATURE_SCHEMA_HASH,
            cost_profile_version=TEST_COST_PROFILE_VERSION,
            training_end_date=self.training_end_date,
        )

    def train(self, batch: PipelineBatch, context: PipelineContext) -> PipelineResult:
        return self._result(PipelineMode.TRAIN, batch, context.horizon)

    def backtest(
        self, batch: PipelineBatch, context: PipelineContext
    ) -> PipelineResult:
        return self._result(PipelineMode.BACKTEST, batch, context.horizon)

    def infer(self, batch: PipelineBatch, context: PipelineContext) -> PipelineResult:
        return self._result(PipelineMode.INFER, batch, context.horizon)
