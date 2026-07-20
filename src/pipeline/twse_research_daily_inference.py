"""Bundle-backed inference for one exact venue research cross-section."""

from __future__ import annotations

# pyright: reportAny=false, reportExplicitAny=false, reportMissingTypeStubs=false
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false

from dataclasses import replace
from datetime import datetime
import json
from math import isfinite
from typing import cast

from src.config.types import MvpConfig
from src.models.stock.rank_model import rank_cross_section
from src.core.research_prediction_contract import (
    research_prediction_contract_version,
)
from src.trading.cost_contracts import TransactionCostConfig
from src.trading.transaction_cost import TransactionCostModel

from .twse_latest_feature_repository import LatestTwseFeatureCrossSection
from .twse_research_decision_contracts import ResearchDecisionPolicyInputs
from .twse_research_decision_policy_adapter import (
    TwseResearchDecisionPolicyAdapter,
)
from .twse_research_loaded_bundle import LoadedTwseResearchBundle
from .twse_research_prediction_contracts import (
    TwseOosResearchPrediction,
    TwseResearchPredictionSnapshot,
)


def _aware(value: object, field_name: str) -> datetime:
    converter = getattr(value, "to_pydatetime", None)
    candidate = converter() if callable(converter) else value
    if not isinstance(candidate, datetime):
        raise ValueError(f"{field_name} must be a datetime")
    if candidate.tzinfo is None or candidate.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return candidate


def _reason_codes(*values: object) -> tuple[str, ...]:
    reasons: list[str] = []
    for value in values:
        if isinstance(value, str):
            try:
                decoded = cast(object, json.loads(value))
            except json.JSONDecodeError:
                decoded = [value]
            if isinstance(decoded, list):
                reasons.extend(str(item) for item in decoded if str(item))
            elif value:
                reasons.append(value)
        elif isinstance(value, (tuple, list)):
            reasons.extend(str(item) for item in value if str(item))
    return tuple(dict.fromkeys(reasons))


def _cost_metadata(config: MvpConfig) -> dict[str, object]:
    return {
        "asset_type": config.cost.asset_type,
        "commission_rate": config.cost.commission_rate,
        "commission_discount": config.cost.commission_discount,
        "minimum_fee": config.cost.minimum_fee,
        "sell_tax_rate": config.cost.sell_tax_rate,
        "estimated_order_notional_ntd": config.cost.estimated_order_notional_ntd,
        "spread_model": config.cost.spread_model,
        "slippage_scenario": config.cost.slippage_scenario,
        "market_impact_parameter": config.cost.market_impact_parameter,
        "max_adv_participation": config.cost.max_adv_participation,
        "selected_profile": "base_cost",
    }


class TwseDailyResearchInference:
    """Score one exact venue without reading current or holdout labels."""

    def __init__(
        self,
        *,
        market: str = "TWSE",
        primary_reason_code: str = "TWSE_PRICE_ONLY_RESEARCH",
    ) -> None:
        normalized = market.strip().upper()
        if normalized not in {"TWSE", "TPEX"}:
            raise ValueError("daily research inference market is unsupported")
        if not primary_reason_code.strip():
            raise ValueError("daily research inference reason code is required")
        self.market = normalized
        self.primary_reason_code = primary_reason_code

    def run(
        self,
        cross_section: LatestTwseFeatureCrossSection,
        bundle: LoadedTwseResearchBundle,
        config: MvpConfig,
    ) -> TwseResearchPredictionSnapshot:
        manifest = bundle.manifest
        frame = cross_section.frame.reset_index(drop=True)
        if config.horizon != 5 or manifest.horizon != 5:
            raise ValueError("UNSUPPORTED_HORIZON")
        if (
            manifest.market != self.market
            or cross_section.market != self.market
            or not frame["market"].eq(self.market).all()
        ):
            raise ValueError("research inference market identity mismatch")
        if manifest.feature_schema_hash != cross_section.manifest.feature_schema_hash:
            raise ValueError("feature schema does not match the model bundle")
        if manifest.training_end_date >= cross_section.as_of_date:
            raise ValueError("model training must precede the inference date")

        decision_ats = {_aware(value, "decision_at") for value in frame["decision_at"]}
        if len(decision_ats) != 1:
            raise ValueError("one inference cross-section must share decision_at")
        decision_at = next(iter(decision_ats))
        evaluation_scope = (
            "RETROSPECTIVE_RESEARCH_INFERENCE"
            if manifest.created_at > decision_at
            else "DAILY_RESEARCH_INFERENCE"
        )
        matrix = bundle.transform(
            frame.loc[:, list(manifest.feature_names)],
            frame["decision_date"].tolist(),
        )
        rank_scores = bundle.predict_rank(matrix)
        directions = bundle.predict_direction(matrix)
        quantiles = bundle.predict_quantiles(matrix)
        if {len(frame), len(rank_scores), len(directions), len(quantiles)} != {
            len(frame)
        }:
            raise ValueError("bundle outputs do not align with feature rows")

        cost_model = TransactionCostModel(
            TransactionCostConfig.from_settings(config.cost)
        )
        costs: list[float] = []
        capacity_reasons: list[tuple[str, ...]] = []
        capacity_passes: list[bool] = []
        maximum_orders: list[float] = []
        for row in frame.itertuples(index=False):
            adv20 = float(row.adv20_ntd)
            estimate = cost_model.estimate_for_decision(
                current_price=float(row.decision_close_price),
                adv20_ntd=adv20,
                horizon=5,
            )
            profile = estimate.profile("base_cost")
            if profile.cost_profile_version != manifest.cost_profile_version:
                raise ValueError("cost profile does not match the model bundle")
            cost_rate = float(profile.round_trip_cost_rate)
            if not isfinite(cost_rate) or cost_rate < 0:
                raise ValueError("inference transaction cost is invalid")
            costs.append(cost_rate)
            capacity_reasons.append(tuple(estimate.reason_codes))
            capacity_passes.append(estimate.capacity_pass)
            maximum_orders.append(adv20 * config.cost.max_adv_participation)

        ranked = rank_cross_section(
            {
                "position": position,
                "decision_date": cross_section.as_of_date,
                "symbol": str(frame.iloc[position]["symbol"]),
                "model_raw_score": rank_scores[position],
            }
            for position in range(len(frame))
        )
        predictions: list[TwseOosResearchPrediction] = []
        policy_adapter = TwseResearchDecisionPolicyAdapter(config)
        for ranked_row in ranked:
            position = int(ranked_row["position"])
            source = frame.iloc[position]
            direction = directions[position]
            quantile = quantiles[position]
            cost = costs[position]
            gross = (
                quantile.gross_q10,
                quantile.gross_q50,
                quantile.gross_q90,
            )
            net = tuple(value - cost for value in gross)
            pit_pass = bool(source["point_in_time_audit_pass"])
            reasons = _reason_codes(
                source["reason_codes"],
                source["research_limitation_reason_codes"],
                capacity_reasons[position],
                (
                    evaluation_scope,
                    "LOCKED_HOLDOUT_NOT_EXECUTED",
                ),
            )
            prediction = TwseOosResearchPrediction(
                symbol=str(source["symbol"]),
                market=self.market,
                decision_date=cross_section.as_of_date,
                decision_at=decision_at,
                horizon=5,
                fold_number=manifest.fold_number,
                model_raw_score=float(ranked_row["model_raw_score"]),
                rank_score=float(ranked_row["rank_score"]),
                global_rank=int(ranked_row["global_rank"]),
                global_rank_percentile=float(ranked_row["global_rank_percentile"]),
                calibrated_p_up=direction.up,
                calibrated_p_neutral=direction.neutral,
                calibrated_p_down=direction.down,
                calibration_version=bundle.probability_calibrator.version,
                gross_q10=gross[0],
                gross_q50=gross[1],
                gross_q90=gross[2],
                net_q10=net[0],
                net_q50=net[1],
                net_q90=net[2],
                interval_width=net[2] - net[0],
                calibration_status=(f"CALIBRATED:{bundle.interval_calibrator.version}"),
                quantile_crossing_before_calibration=quantile.raw_crossed,
                estimated_round_trip_cost=cost,
                latest_available_at=_aware(
                    source["latest_available_at"], "latest_available_at"
                ),
                data_quality_status="PASS" if pit_pass else "WARN",
                reason_codes=reasons,
                adv20_ntd=float(source["adv20_ntd"]),
                maximum_order_notional_ntd=maximum_orders[position],
                evaluation_scope=evaluation_scope,
            )
            policy = policy_adapter.evaluate(
                prediction,
                ResearchDecisionPolicyInputs(
                    data_quality_hard_fail=bool(source["hard_fail"]),
                    liquidity_pass=capacity_passes[position],
                    estimated_order_notional_ntd=(
                        config.cost.estimated_order_notional_ntd
                    ),
                    gate_source_dates={
                        "data_quality_hard_gate": cross_section.as_of_date,
                        "liquidity_capacity_gate": cross_section.as_of_date,
                    },
                ),
            )
            predictions.append(
                replace(
                    prediction,
                    gates=policy.gates,
                    reason_codes=tuple(
                        dict.fromkeys((*prediction.reason_codes, *policy.reason_codes))
                    ),
                )
            )

        return TwseResearchPredictionSnapshot(
            as_of_date=cross_section.as_of_date,
            decision_at=decision_at,
            horizon=5,
            predictions=tuple(predictions),
            model_version=manifest.model_version,
            feature_schema_hash=manifest.feature_schema_hash,
            dataset_snapshot_id=cross_section.manifest.dataset_snapshot_sha256,
            source_hash=cross_section.manifest.source_archive_snapshot_sha256,
            input_artifact_sha256=cross_section.manifest.parquet_sha256,
            label_version=manifest.label_version,
            benchmark_id=manifest.benchmark_id,
            benchmark_version=manifest.benchmark_version,
            cost_profile_version=manifest.cost_profile_version,
            training_end_date=manifest.training_end_date,
            model_metadata={
                "model_bundle_sha256": manifest.manifest_sha256,
                "model_bundle_contract_version": manifest.contract_version,
                "selection_policy": manifest.selection_policy,
                "fold_number": manifest.fold_number,
                "training_start_date": manifest.training_start_date.isoformat(),
                "calibration_start_date": (manifest.calibration_start_date.isoformat()),
                "calibration_end_date": manifest.calibration_end_date.isoformat(),
                "evaluated_test_start_date": (
                    manifest.evaluated_test_start_date.isoformat()
                ),
                "evaluated_test_end_date": (
                    manifest.evaluated_test_end_date.isoformat()
                ),
                "library_versions": dict(manifest.library_versions),
                "git_commit": manifest.git_commit,
                "research_run_provenance": (
                    dict(manifest.research_run_provenance)
                    if manifest.research_run_provenance is not None
                    else None
                ),
                "feature_artifact_manifest": (cross_section.manifest.to_dict()),
            },
            cost_metadata=_cost_metadata(config),
            validation={
                "system_status": "RESEARCH_ONLY",
                "evaluation_scope": evaluation_scope,
                "locked_holdout_executed": False,
                "research_decision_policy_executed": True,
                "formal_decision_policy_executed": False,
                "source_model_test_end_date": (
                    manifest.evaluated_test_end_date.isoformat()
                ),
            },
            reason_codes=(
                self.primary_reason_code,
                evaluation_scope,
                "LATEST_VERIFIED_FEATURE_CROSS_SECTION",
                "POINT_IN_TIME_UNVERIFIED",
                "LOCKED_HOLDOUT_NOT_EXECUTED",
                "RESEARCH_DECISION_POLICY_EXECUTED_FAIL_CLOSED",
                "FORMAL_TRADABILITY_INPUT_MISSING",
                "FORMAL_MARKET_EXPOSURE_INPUT_MISSING",
                "FORMAL_POSITION_LIMIT_INPUT_MISSING",
            ),
            market=self.market,
            artifact_contract_version=research_prediction_contract_version(self.market),
        )


__all__ = ["TwseDailyResearchInference"]
