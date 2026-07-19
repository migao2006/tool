"""Explicitly gated Staging publisher for verified TWSE research JSON artifacts."""

from __future__ import annotations

# pyright: reportAny=false, reportExplicitAny=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
import re
from typing import cast, final

from src.core.research_prediction_contract import (
    RESEARCH_PREDICTION_CONTRACT_VERSION,
)
from src.data.research.twse_research_prediction_supabase_contracts import (
    ResearchSupabasePublishResult,
    SupabaseResearchWriter,
)


def _required(payload: Mapping[str, object], name: str) -> object:
    value = payload.get(name)
    if value is None or value == "":
        raise ValueError(f"research prediction artifact is missing {name}")
    return value


def _verify_snapshot_hash(payload: Mapping[str, object]) -> str:
    expected = str(_required(payload, "snapshot_sha256"))
    content = dict(payload)
    _ = content.pop("snapshot_sha256", None)
    actual = sha256(
        json.dumps(
            content,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    if expected != actual:
        raise ValueError("research prediction snapshot hash mismatch")
    return actual


@final
class TwseResearchPredictionSupabasePublisher:
    """Write research rows only after two explicit non-Production gates."""

    def __init__(
        self,
        writer: SupabaseResearchWriter,
        *,
        target_environment: str,
        publish_enabled: bool,
    ) -> None:
        environment = target_environment.strip().lower()
        if not publish_enabled:
            raise ValueError("RESEARCH_PREDICTION_SUPABASE_PUBLISH_ENABLED is false")
        if environment not in {"development", "staging"}:
            raise ValueError(
                "research prediction publishing is limited to development/staging"
            )
        self.writer = writer
        self.target_environment = environment

    def publish(
        self,
        payload: Mapping[str, object],
    ) -> ResearchSupabasePublishResult:
        snapshot_hash = _verify_snapshot_hash(payload)
        if payload.get("artifact_contract_version") != (
            RESEARCH_PREDICTION_CONTRACT_VERSION
        ):
            raise ValueError("unsupported research prediction artifact version")
        if payload.get("system_status") != "RESEARCH_ONLY":
            raise ValueError("only RESEARCH_ONLY snapshots can use this publisher")
        if payload.get("horizon") != 5:
            raise ValueError("UNSUPPORTED_HORIZON")
        for name in ("model_metadata", "cost_metadata", "validation"):
            if not isinstance(payload.get(name), Mapping):
                raise ValueError(f"research prediction {name} must be an object")
        raw_predictions_value = payload.get("predictions")
        if not isinstance(raw_predictions_value, list) or not raw_predictions_value:
            raise ValueError("research prediction artifact has no predictions")
        raw_predictions = raw_predictions_value
        predictions = [
            cast(Mapping[str, object], value)
            for value in raw_predictions
            if isinstance(value, Mapping)
        ]
        if len(predictions) != len(raw_predictions):
            raise ValueError("research prediction rows must be JSON objects")
        snapshot_date = _required(payload, "as_of_date")
        snapshot_decision_at = _required(payload, "decision_at")
        for prediction in predictions:
            if (
                prediction.get("horizon") != 5
                or prediction.get("market") != "TWSE"
                or prediction.get("evaluation_scope") != "OUT_OF_SAMPLE_TEST"
                or prediction.get("decision_date") != snapshot_date
                or prediction.get("decision_at") != snapshot_decision_at
                or prediction.get("data_quality_status") not in {"PASS", "WARN"}
            ):
                raise ValueError("research prediction row does not match the snapshot")

        security_ids = self._security_ids(predictions)
        self._ensure_cost_profile(payload)
        run_id = self._upsert_run(payload, predictions, snapshot_hash)
        rows = [
            self._stock_row(run_id, prediction, security_ids)
            for prediction in predictions
        ]
        _ = self.writer.upsert(
            "stock_predictions",
            rows,
            on_conflict="prediction_run_id,security_id",
        )
        return ResearchSupabasePublishResult(
            prediction_run_id=run_id,
            prediction_count=len(rows),
            target_environment=self.target_environment,
        )

    def _security_ids(
        self,
        predictions: Sequence[Mapping[str, object]],
    ) -> dict[str, int]:
        symbols = tuple(str(_required(value, "symbol")) for value in predictions)
        if len(set(symbols)) != len(symbols):
            raise ValueError("research prediction symbols must be unique")
        if any(re.fullmatch(r"[0-9A-Z]{2,12}", symbol) is None for symbol in symbols):
            raise ValueError("research prediction contains an unsafe symbol")
        escaped = list(symbols)
        records: list[dict[str, object]] = []
        for offset in range(0, len(escaped), 200):
            batch = escaped[offset : offset + 200]
            records.extend(
                self.writer.select_rows(
                    "securities",
                    select="security_id,symbol,market,asset_type",
                    filters={
                        "market": "eq.TWSE",
                        "asset_type": "eq.COMMON_STOCK",
                        "symbol": f"in.({','.join(batch)})",
                    },
                    limit=len(batch),
                )
            )
        mapping = {
            str(row["symbol"]): int(cast(int | str, row["security_id"]))
            for row in records
            if row.get("market") == "TWSE" and row.get("asset_type") == "COMMON_STOCK"
        }
        missing = sorted(set(symbols).difference(mapping))
        if missing:
            raise ValueError(
                "research prediction securities are unresolved: " + ", ".join(missing)
            )
        return mapping

    def _ensure_cost_profile(self, payload: Mapping[str, object]) -> None:
        metadata_value = payload.get("cost_metadata")
        if not isinstance(metadata_value, Mapping):
            raise ValueError("research prediction cost_metadata must be an object")
        metadata = cast(Mapping[str, object], metadata_value)
        fields = (
            "asset_type",
            "commission_rate",
            "commission_discount",
            "minimum_fee",
            "sell_tax_rate",
            "estimated_order_notional_ntd",
            "spread_model",
            "slippage_scenario",
            "market_impact_parameter",
            "max_adv_participation",
        )
        row = {name: _required(metadata, name) for name in fields}
        row["cost_profile_version"] = _required(payload, "cost_profile_version")
        row["parameters"] = {
            "research_snapshot_sha256": _required(payload, "snapshot_sha256")
        }
        _ = self.writer.upsert(
            "cost_profiles",
            [row],
            on_conflict="cost_profile_version",
            preserve_existing=True,
        )

    def _upsert_run(
        self,
        payload: Mapping[str, object],
        predictions: Sequence[Mapping[str, object]],
        snapshot_hash: str,
    ) -> int:
        latest_available_at = max(
            str(_required(value, "latest_available_at")) for value in predictions
        )
        model_version = str(_required(payload, "model_version"))
        returned = self.writer.upsert(
            "prediction_runs",
            [
                {
                    "as_of_date": _required(payload, "as_of_date"),
                    "decision_at": _required(payload, "decision_at"),
                    "horizon": 5,
                    "model_bundle_version": (
                        f"{model_version}:oos-research:{snapshot_hash[:12]}"
                    ),
                    "feature_schema_hash": _required(payload, "feature_schema_hash"),
                    "benchmark_versions": {
                        "TWSE": _required(payload, "benchmark_version")
                    },
                    "cost_profile_version": _required(payload, "cost_profile_version"),
                    "training_end_date": _required(payload, "training_end_date"),
                    "system_validation_status": "RESEARCH_ONLY",
                    "source_dates": {
                        "prepared_dataset": _required(payload, "as_of_date")
                    },
                    "latest_available_at": latest_available_at,
                    "candidate_count": 0,
                    "watch_count": 0,
                    "no_trade_count": len(predictions),
                    "hard_fail_count": sum(
                        value.get("data_quality_status") != "PASS"
                        for value in predictions
                    ),
                }
            ],
            on_conflict="decision_at,horizon,model_bundle_version",
            select="prediction_run_id",
            return_rows=True,
        )
        if len(returned) != 1 or "prediction_run_id" not in returned[0]:
            raise ValueError("Supabase did not return one prediction_run_id")
        return int(cast(int | str, returned[0]["prediction_run_id"]))

    @staticmethod
    def _stock_row(
        run_id: int,
        prediction: Mapping[str, object],
        security_ids: Mapping[str, int],
    ) -> dict[str, object]:
        symbol = str(_required(prediction, "symbol"))
        original_quality = str(_required(prediction, "data_quality_status"))
        reasons = prediction.get("reason_codes")
        if not isinstance(reasons, list):
            raise ValueError("research prediction reason_codes must be an array")
        reason_codes = [str(value) for value in cast(list[object], reasons)]
        reason_codes.append("RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY")
        if original_quality == "WARN":
            reason_codes.append("RESEARCH_DATA_QUALITY_WARN")
        return {
            "prediction_run_id": run_id,
            "security_id": security_ids[symbol],
            "market": "TWSE",
            "model_raw_score": _required(prediction, "model_raw_score"),
            "rank_score": _required(prediction, "rank_score"),
            "global_rank": _required(prediction, "global_rank"),
            "global_rank_percentile": _required(prediction, "global_rank_percentile"),
            "calibrated_p_up": _required(prediction, "calibrated_p_up"),
            "calibrated_p_neutral": _required(prediction, "calibrated_p_neutral"),
            "calibrated_p_down": _required(prediction, "calibrated_p_down"),
            "calibration_version": _required(prediction, "calibration_version"),
            "gross_q10": _required(prediction, "gross_q10"),
            "gross_q50": _required(prediction, "gross_q50"),
            "gross_q90": _required(prediction, "gross_q90"),
            "net_q10": _required(prediction, "net_q10"),
            "net_q50": _required(prediction, "net_q50"),
            "net_q90": _required(prediction, "net_q90"),
            "interval_width": _required(prediction, "interval_width"),
            "quantile_crossing_before_calibration": _required(
                prediction, "quantile_crossing_before_calibration"
            ),
            "calibration_status": _required(prediction, "calibration_status"),
            "estimated_round_trip_cost": _required(
                prediction, "estimated_round_trip_cost"
            ),
            "data_quality_status": ("PASS" if original_quality == "PASS" else "FAIL"),
            "decision": "NO_TRADE",
            "reason_codes": list(dict.fromkeys(reason_codes)),
        }


__all__ = [
    "ResearchSupabasePublishResult",
    "TwseResearchPredictionSupabasePublisher",
]
