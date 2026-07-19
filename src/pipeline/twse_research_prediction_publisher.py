"""Assemble and atomically persist the latest TWSE OOS research cross-section."""

# pyright: reportAny=false, reportExplicitAny=false, reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false, reportUnusedCallResult=false

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.models.stock.rank_model import rank_cross_section

from .twse_research_evaluation_contracts import (
    DirectionEvaluation,
    QuantileEvaluation,
    RankEvaluation,
)
from .twse_research_prediction_contracts import (
    TwseOosResearchPrediction,
    TwseResearchPredictionSnapshot,
)
from .twse_research_snapshot_writer import persist_research_snapshot


@dataclass(frozen=True)
class FoldResearchPredictionBatch:
    fold_number: int
    training_end_date: date
    predictions: tuple[TwseOosResearchPrediction, ...]

    def __post_init__(self) -> None:
        if self.fold_number < 0 or not self.predictions:
            raise ValueError("a fold batch requires a non-negative fold and predictions")
        if any(value.fold_number != self.fold_number for value in self.predictions):
            raise ValueError("prediction fold_number does not match its fold batch")


@dataclass(frozen=True)
class PublishedResearchSnapshot:
    path: Path
    artifact_sha256: str
    snapshot: TwseResearchPredictionSnapshot


def _aware_datetime(value: Any, field_name: str) -> datetime:
    candidate = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    if not isinstance(candidate, datetime):
        raise ValueError(f"{field_name} must be a datetime")
    if candidate.tzinfo is None or candidate.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return candidate


def build_fold_research_predictions(
    *,
    frame: Any,
    train_indices: Sequence[int],
    test_indices: Sequence[int],
    fold_number: int,
    rank: RankEvaluation,
    direction: DirectionEvaluation,
    quantiles: QuantileEvaluation,
) -> FoldResearchPredictionBatch:
    """Bind three independently evaluated models to the same OOS test rows."""

    positions = list(test_indices)
    lengths = {
        len(positions),
        len(rank.model_scores),
        len(direction.probabilities),
        len(quantiles.gross_quantiles),
        len(quantiles.net_quantiles),
        len(quantiles.raw_crossed),
    }
    if lengths != {len(positions)} or not positions:
        raise ValueError("all OOS model outputs must align with test_indices")
    if fold_number < 0 or not train_indices:
        raise ValueError("non-negative fold_number and train_indices are required")

    source_columns = [
        "symbol",
        "decision_date",
        "decision_at",
        "available_at",
        "horizon",
        "round_trip_cost_rate",
        "data_quality_status",
        "reason_codes",
    ]
    rows = frame[source_columns].iloc[positions]
    rank_inputs = [
        {
            "position": offset,
            "decision_date": row.decision_date,
            "symbol": str(row.symbol),
            "model_raw_score": rank.model_scores[offset],
        }
        for offset, row in enumerate(rows.itertuples())
    ]
    ranked = rank_cross_section(rank_inputs)
    predictions: list[TwseOosResearchPrediction] = []
    for ranked_row in ranked:
        offset = int(ranked_row["position"])
        source = rows.iloc[offset]
        gross = quantiles.gross_quantiles[offset]
        net = quantiles.net_quantiles[offset]
        probabilities = direction.probabilities[offset]
        reasons = source["reason_codes"]
        if not isinstance(reasons, (tuple, list)):
            raise ValueError("research row reason_codes must be a sequence")
        predictions.append(
            TwseOosResearchPrediction(
                symbol=str(source["symbol"]),
                decision_date=source["decision_date"],
                decision_at=_aware_datetime(source["decision_at"], "decision_at"),
                horizon=int(source["horizon"]),
                fold_number=fold_number,
                model_raw_score=float(ranked_row["model_raw_score"]),
                rank_score=float(ranked_row["rank_score"]),
                global_rank=int(ranked_row["global_rank"]),
                global_rank_percentile=float(ranked_row["global_rank_percentile"]),
                calibrated_p_up=probabilities[0],
                calibrated_p_neutral=probabilities[1],
                calibrated_p_down=probabilities[2],
                calibration_version=direction.calibration_version,
                gross_q10=gross[0],
                gross_q50=gross[1],
                gross_q90=gross[2],
                net_q10=net[0],
                net_q50=net[1],
                net_q90=net[2],
                interval_width=net[2] - net[0],
                calibration_status=(f"CALIBRATED:{quantiles.calibration_version}"),
                quantile_crossing_before_calibration=(quantiles.raw_crossed[offset]),
                estimated_round_trip_cost=float(source["round_trip_cost_rate"]),
                latest_available_at=_aware_datetime(
                    source["available_at"], "available_at"
                ),
                data_quality_status=str(source["data_quality_status"]).upper(),
                reason_codes=tuple(str(value) for value in reasons),
            )
        )
    training_end_date = max(frame["decision_date"].iloc[list(train_indices)])
    return FoldResearchPredictionBatch(
        fold_number=fold_number,
        training_end_date=training_end_date,
        predictions=tuple(predictions),
    )


class TwseResearchPredictionPublisher:
    """Select the latest completed OOS date and write one immutable JSON artifact."""

    def publish(
        self,
        path: Path,
        *,
        fold_batches: Sequence[FoldResearchPredictionBatch],
        horizon: int,
        model_version: str,
        feature_schema_hash: str,
        input_artifact_sha256: str,
        provenance: Mapping[str, str],
        model_metadata: Mapping[str, object],
        cost_metadata: Mapping[str, object],
        validation: Mapping[str, object],
        reason_codes: tuple[str, ...],
    ) -> PublishedResearchSnapshot:
        if not fold_batches:
            raise ValueError("at least one OOS fold batch is required")
        all_predictions = [
            prediction for batch in fold_batches for prediction in batch.predictions
        ]
        latest_date = max(value.decision_date for value in all_predictions)
        latest_fold = max(
            value.fold_number
            for value in all_predictions
            if value.decision_date == latest_date
        )
        selected = tuple(
            sorted(
                (
                    value
                    for value in all_predictions
                    if value.decision_date == latest_date
                    and value.fold_number == latest_fold
                ),
                key=lambda value: value.global_rank,
            )
        )
        matching_batch = next(
            batch for batch in fold_batches if batch.fold_number == latest_fold
        )
        decision_ats = {value.decision_at for value in selected}
        if len(decision_ats) != 1:
            raise ValueError("one OOS cross-section must share a decision_at")
        required_provenance = (
            "dataset_snapshot_id",
            "source_hash",
            "label_version",
            "benchmark_id",
            "benchmark_version",
            "cost_profile_version",
        )
        missing = [name for name in required_provenance if not provenance.get(name)]
        if missing:
            raise ValueError(
                "research prediction provenance is missing: " + ", ".join(missing)
            )
        snapshot = TwseResearchPredictionSnapshot(
            as_of_date=latest_date,
            decision_at=next(iter(decision_ats)),
            horizon=horizon,
            predictions=selected,
            model_version=model_version,
            feature_schema_hash=feature_schema_hash,
            dataset_snapshot_id=provenance["dataset_snapshot_id"],
            source_hash=provenance["source_hash"],
            input_artifact_sha256=input_artifact_sha256,
            label_version=provenance["label_version"],
            benchmark_id=provenance["benchmark_id"],
            benchmark_version=provenance["benchmark_version"],
            cost_profile_version=provenance["cost_profile_version"],
            training_end_date=matching_batch.training_end_date,
            model_metadata=dict(model_metadata),
            cost_metadata=dict(cost_metadata),
            validation=dict(validation),
            reason_codes=reason_codes,
        )
        persisted = persist_research_snapshot(path, snapshot)
        return PublishedResearchSnapshot(
            path=path,
            artifact_sha256=persisted.artifact_sha256,
            snapshot=snapshot,
        )


__all__ = [
    "FoldResearchPredictionBatch",
    "PublishedResearchSnapshot",
    "TwseResearchPredictionPublisher",
    "build_fold_research_predictions",
]
