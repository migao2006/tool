from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
from typing import cast, override

import pytest

from src.core.research_prediction_contract import (
    RESEARCH_PREDICTION_CONTRACT_VERSION,
    TPEX_RESEARCH_PREDICTION_CONTRACT_VERSION,
)
from src.decision.decision_policy import DECISION_GATE_ORDER
from src.data.research.twse_research_prediction_supabase import (
    TpexResearchPredictionSupabasePublisher,
    TwseResearchPredictionSupabasePublisher,
)


class _Writer:
    def __init__(self, *, persist_cost_profiles: bool = True) -> None:
        self.upserts: list[tuple[str, list[dict[str, object]]]] = []
        self.rpc_calls: list[tuple[str, dict[str, object]]] = []
        self.cost_profiles: dict[str, dict[str, object]] = {}
        self.stock_predictions: list[dict[str, object]] = []
        self.persist_cost_profiles: bool = persist_cost_profiles

    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]:
        del select, limit
        if table == "cost_profiles":
            assert filters is not None
            version_filter = filters["cost_profile_version"]
            assert version_filter.startswith("eq.")
            stored = self.cost_profiles.get(version_filter.removeprefix("eq."))
            return [] if stored is None else [dict(stored)]
        if table == "stock_predictions":
            return [dict(value) for value in self.stock_predictions]
        assert table == "securities"
        return [
            {
                "security_id": 2330,
                "symbol": "2330",
                "market": "TWSE",
                "asset_type": "COMMON_STOCK",
            }
        ]

    def upsert(
        self,
        table: str,
        rows: Sequence[Mapping[str, object]],
        *,
        on_conflict: str,
        select: str | None = None,
        return_rows: bool = False,
        preserve_existing: bool = False,
    ) -> list[dict[str, object]]:
        del select
        materialized = [dict(value) for value in rows]
        self.upserts.append((table, materialized))
        if table == "cost_profiles" and self.persist_cost_profiles:
            assert on_conflict == "cost_profile_version"
            assert preserve_existing
            for row in materialized:
                version = str(row["cost_profile_version"])
                if version not in self.cost_profiles:
                    self.cost_profiles[version] = dict(row)
        if table == "decision_gate_results" and return_rows:
            return materialized
        return []

    def rpc(
        self,
        function_name: str,
        parameters: Mapping[str, object],
    ) -> object:
        self.rpc_calls.append((function_name, dict(parameters)))
        predictions = cast(list[dict[str, object]], parameters["p_stock_predictions"])
        self.stock_predictions = [
            {"stock_prediction_id": index, **dict(value)}
            for index, value in enumerate(predictions, start=1)
        ]
        run = cast(dict[str, object], parameters["p_run"])
        return {
            "prediction_run_id": 7,
            "prediction_count": len(predictions),
            "market_scope": run["market_scope"],
        }


class _DatabaseRoundedWriter(_Writer):
    def __init__(self, *, stored_p_up: object = "0.60000000") -> None:
        super().__init__()
        self.stored_p_up = stored_p_up

    @override
    def rpc(
        self,
        function_name: str,
        parameters: Mapping[str, object],
    ) -> object:
        result = super().rpc(function_name, parameters)
        self.stock_predictions[0]["calibrated_p_up"] = self.stored_p_up
        self.stock_predictions[0]["calibrated_p_neutral"] = "0.30000000"
        return result


def _payload(
    *,
    evaluation_scope: str = "OUT_OF_SAMPLE_TEST",
    model_bundle_sha256: str | None = None,
    include_gates: bool = False,
    legacy_policy_contract: bool = False,
) -> dict[str, object]:
    prediction = {
        "symbol": "2330",
        "market": "TWSE",
        "decision_date": "2026-01-02",
        "decision_at": "2026-01-02T06:30:00+00:00",
        "horizon": 5,
        "fold_number": 0,
        "evaluation_scope": evaluation_scope,
        "model_raw_score": 0.8,
        "rank_score": 100.0,
        "global_rank": 1,
        "global_rank_percentile": 1.0,
        "calibrated_p_up": 0.6,
        "calibrated_p_neutral": 0.3,
        "calibrated_p_down": 0.1,
        "calibration_version": "probability-calibration-v1",
        "gross_q10": -0.02,
        "gross_q50": 0.01,
        "gross_q90": 0.05,
        "net_q10": -0.026,
        "net_q50": 0.004,
        "net_q90": 0.044,
        "interval_width": 0.07,
        "calibration_status": "CALIBRATED:interval-calibration-v1",
        "quantile_crossing_before_calibration": False,
        "estimated_round_trip_cost": 0.006,
        "latest_available_at": "2026-01-02T06:00:00+00:00",
        "data_quality_status": "WARN",
        "decision": None,
        "decision_policy_status": "MISSING_REQUIRED_DATA",
        "reason_codes": ["TWSE_PRICE_ONLY_RESEARCH"],
    }
    if legacy_policy_contract:
        prediction["decision"] = "NO_TRADE"
        del prediction["decision_policy_status"]
    if include_gates:
        prediction["gates"] = [
            {
                "gate": gate,
                "passed": gate
                in {
                    "liquidity_capacity_gate",
                    "calibrated_direction_probabilities",
                    "net_quantile_thresholds",
                    "rank_eligibility",
                },
                "actual": {"gate": gate},
                "threshold": {"configured": True},
                "reason_code": (
                    "PASS"
                    if gate
                    in {
                        "liquidity_capacity_gate",
                        "calibrated_direction_probabilities",
                        "net_quantile_thresholds",
                        "rank_eligibility",
                    }
                    else "FORMAL_INPUT_MISSING"
                ),
                "source_date": (
                    "2026-01-02"
                    if gate
                    in {
                        "data_quality_hard_gate",
                        "liquidity_capacity_gate",
                        "calibrated_direction_probabilities",
                        "net_quantile_thresholds",
                        "rank_eligibility",
                    }
                    else None
                ),
            }
            for gate in DECISION_GATE_ORDER
        ]
    payload: dict[str, object] = {
        "artifact_contract_version": RESEARCH_PREDICTION_CONTRACT_VERSION,
        "system_status": "RESEARCH_ONLY",
        "as_of_date": "2026-01-02",
        "decision_at": "2026-01-02T06:30:00+00:00",
        "horizon": 5,
        "predictions": [prediction],
        "model_version": "twse-price-research-h5-v1",
        "feature_schema_hash": "f" * 64,
        "dataset_snapshot_id": "d" * 64,
        "source_hash": "a" * 64,
        "input_artifact_sha256": "b" * 64,
        "label_version": "label-v1",
        "benchmark_id": "TAIEX",
        "benchmark_version": "benchmark-v1",
        "cost_profile_version": "cost-v1",
        "training_end_date": "2025-12-31",
        "model_metadata": {"rank_model": "LightGBM"},
        "cost_metadata": {
            "asset_type": "COMMON_STOCK",
            "commission_rate": 0.001425,
            "commission_discount": 1.0,
            "minimum_fee": 20.0,
            "sell_tax_rate": 0.003,
            "estimated_order_notional_ntd": 100000.0,
            "spread_model": "tick_liquidity_adv20_v1",
            "slippage_scenario": "base",
            "market_impact_parameter": 0.001,
            "max_adv_participation": 0.01,
        },
        "validation": {"fold_count": 1},
        "reason_codes": ["TWSE_PRICE_ONLY_RESEARCH"],
    }
    if model_bundle_sha256 is not None:
        cast(dict[str, object], payload["model_metadata"])["model_bundle_sha256"] = (
            model_bundle_sha256
        )
    payload["snapshot_sha256"] = sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return payload


def _tpex_payload() -> dict[str, object]:
    payload = _payload()
    payload["market"] = "TPEX"
    payload["artifact_contract_version"] = TPEX_RESEARCH_PREDICTION_CONTRACT_VERSION
    predictions = cast(list[dict[str, object]], payload["predictions"])
    predictions[0]["market"] = "TPEX"
    predictions[0]["reason_codes"] = ["TPEX_PRICE_ONLY_RESEARCH"]
    payload["benchmark_id"] = "TPEX_PRICE_INDEX"
    payload["snapshot_sha256"] = sha256(
        json.dumps(
            {key: value for key, value in payload.items() if key != "snapshot_sha256"},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return payload


class _TpexWriter(_Writer):
    @override
    def select_rows(
        self,
        table: str,
        *,
        select: str,
        filters: Mapping[str, str] | None = None,
        limit: int = 1_000,
    ) -> list[dict[str, object]]:
        if table != "securities":
            return super().select_rows(table, select=select, filters=filters, limit=limit)
        assert filters is not None
        assert filters["market"] == "eq.TPEX"
        return [
            {
                "security_id": 92330,
                "symbol": "2330",
                "market": "TPEX",
                "asset_type": "COMMON_STOCK",
            }
        ]


def test_staging_publish_is_conservative_and_idempotent() -> None:
    writer = _Writer()
    result = TwseResearchPredictionSupabasePublisher(
        writer,
        target_environment="staging",
        publish_enabled=True,
    ).publish(_payload())

    assert result.prediction_run_id == 7
    assert result.prediction_count == 1
    assert [value[0] for value in writer.upserts] == ["cost_profiles"]
    assert writer.cost_profiles["cost-v1"]["parameters"] == {}
    assert len(writer.rpc_calls) == 1
    function_name, parameters = writer.rpc_calls[0]
    assert function_name == "publish_research_prediction_snapshot"
    run = cast(dict[str, object], parameters["p_run"])
    stock = cast(list[dict[str, object]], parameters["p_stock_predictions"])[0]
    assert run["system_validation_status"] == "RESEARCH_ONLY"
    assert run["candidate_count"] == 0
    assert run["no_trade_count"] == 0
    assert run["policy_input_missing_count"] == 1
    assert run["policy_validation_failed_count"] == 0
    assert run["policy_hard_fail_count"] == 0
    assert run["hard_fail_count"] == 0
    assert run["model_bundle_version"] == ("twse-price-research-h5-v1:oos-research")
    source_dates = cast(dict[str, object], run["source_dates"])
    assert source_dates["prediction_scope"] == "OUT_OF_SAMPLE_TEST"
    assert source_dates["feature_snapshot"] == "b" * 64
    assert source_dates["decision_gate_count"] == 0
    assert source_dates["decision_gate_attachment_contract"] == ("research-decision-gate.v1")
    assert stock["decision"] is None
    assert stock["decision_policy_status"] == "MISSING_REQUIRED_DATA"
    assert stock["data_quality_status"] == "WARN"
    assert "RESEARCH_DATA_QUALITY_WARN" in cast(list[object], stock["reason_codes"])


def test_unclassified_legacy_no_trade_is_fail_closed_as_validation() -> None:
    writer = _Writer()

    _ = TwseResearchPredictionSupabasePublisher(
        writer,
        target_environment="staging",
        publish_enabled=True,
    ).publish(_payload(legacy_policy_contract=True))

    _, parameters = writer.rpc_calls[0]
    run = cast(dict[str, object], parameters["p_run"])
    stock = cast(list[dict[str, object]], parameters["p_stock_predictions"])[0]
    assert run["no_trade_count"] == 0
    assert run["policy_input_missing_count"] == 0
    assert run["policy_validation_failed_count"] == 1
    assert stock["decision"] is None
    assert stock["decision_policy_status"] == "VALIDATION_FAILED"
    assert "DECISION_POLICY_VALIDATION_FAILED" in cast(list[object], stock["reason_codes"])


def test_evaluated_research_action_requires_pass_quality_and_gate_evidence() -> None:
    payload = _payload(include_gates=True)
    prediction = cast(list[dict[str, object]], payload["predictions"])[0]
    prediction["decision"] = "NO_TRADE"
    prediction["decision_policy_status"] = "EVALUATED"
    gates = cast(list[dict[str, object]], prediction["gates"])
    for gate in gates:
        gate["source_date"] = "2026-01-02"
    payload["snapshot_sha256"] = sha256(
        json.dumps(
            {key: value for key, value in payload.items() if key != "snapshot_sha256"},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(ValueError, match="requires PASS data quality"):
        _ = TwseResearchPredictionSupabasePublisher(
            _Writer(),
            target_environment="staging",
            publish_enabled=True,
        ).publish(payload)

    prediction["data_quality_status"] = "PASS"
    payload["snapshot_sha256"] = sha256(
        json.dumps(
            {key: value for key, value in payload.items() if key != "snapshot_sha256"},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    writer = _Writer()
    _ = TwseResearchPredictionSupabasePublisher(
        writer,
        target_environment="staging",
        publish_enabled=True,
    ).publish(payload)

    _, parameters = writer.rpc_calls[0]
    run = cast(dict[str, object], parameters["p_run"])
    stock = cast(list[dict[str, object]], parameters["p_stock_predictions"])[0]
    assert run["no_trade_count"] == 1
    assert run["policy_validation_failed_count"] == 0
    assert stock["decision"] == "NO_TRADE"
    assert stock["decision_policy_status"] == "EVALUATED"


def test_hard_fail_status_and_quality_are_published_without_collapsing() -> None:
    writer = _Writer()
    payload = _payload()
    prediction = cast(list[dict[str, object]], payload["predictions"])[0]
    prediction["data_quality_status"] = "HARD_FAIL"
    prediction["decision"] = None
    prediction["decision_policy_status"] = "HARD_FAIL"
    prediction["reason_codes"] = ["DUPLICATE_CANONICAL_BAR"]
    payload["snapshot_sha256"] = sha256(
        json.dumps(
            {key: value for key, value in payload.items() if key != "snapshot_sha256"},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    _ = TwseResearchPredictionSupabasePublisher(
        writer,
        target_environment="staging",
        publish_enabled=True,
    ).publish(payload)

    _, parameters = writer.rpc_calls[0]
    run = cast(dict[str, object], parameters["p_run"])
    stock = cast(list[dict[str, object]], parameters["p_stock_predictions"])[0]
    assert run["policy_hard_fail_count"] == 1
    assert run["hard_fail_count"] == 1
    assert run["no_trade_count"] == 0
    assert stock["decision"] is None
    assert stock["decision_policy_status"] == "HARD_FAIL"
    assert stock["data_quality_status"] == "HARD_FAIL"
    assert "DUPLICATE_CANONICAL_BAR" in cast(list[object], stock["reason_codes"])


def test_legacy_hard_fail_quality_is_not_reclassified_as_missing() -> None:
    writer = _Writer()
    payload = _payload(legacy_policy_contract=True)
    prediction = cast(list[dict[str, object]], payload["predictions"])[0]
    prediction["data_quality_status"] = "HARD_FAIL"
    prediction["decision"] = "NO_TRADE"
    prediction["reason_codes"] = ["DUPLICATE_CANONICAL_BAR"]
    payload["snapshot_sha256"] = sha256(
        json.dumps(
            {key: value for key, value in payload.items() if key != "snapshot_sha256"},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    _ = TwseResearchPredictionSupabasePublisher(
        writer,
        target_environment="staging",
        publish_enabled=True,
    ).publish(payload)

    _, parameters = writer.rpc_calls[0]
    run = cast(dict[str, object], parameters["p_run"])
    stock = cast(list[dict[str, object]], parameters["p_stock_predictions"])[0]
    assert run["policy_input_missing_count"] == 0
    assert run["policy_hard_fail_count"] == 1
    assert stock["decision"] is None
    assert stock["decision_policy_status"] == "HARD_FAIL"
    assert stock["data_quality_status"] == "HARD_FAIL"
    assert "DATA_QUALITY_HARD_FAIL" in cast(list[object], stock["reason_codes"])


def test_hard_fail_status_and_quality_mismatch_is_rejected_before_write() -> None:
    writer = _Writer()
    payload = _payload()
    prediction = cast(list[dict[str, object]], payload["predictions"])[0]
    prediction["decision_policy_status"] = "HARD_FAIL"
    payload["snapshot_sha256"] = sha256(
        json.dumps(
            {key: value for key, value in payload.items() if key != "snapshot_sha256"},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(
        ValueError,
        match="HARD_FAIL policy status and research data quality must agree",
    ):
        _ = TwseResearchPredictionSupabasePublisher(
            writer,
            target_environment="staging",
            publish_enabled=True,
        ).publish(payload)

    assert writer.upserts == []
    assert writer.rpc_calls == []


def test_gated_research_snapshot_persists_all_eight_verified_gate_rows() -> None:
    writer = _Writer()

    result = TwseResearchPredictionSupabasePublisher(
        writer,
        target_environment="staging",
        publish_enabled=True,
    ).publish(_payload(include_gates=True))

    assert result.decision_gate_count == 8
    tables = [value[0] for value in writer.upserts]
    assert tables == ["cost_profiles", "decision_gate_results"]
    gate_rows = writer.upserts[-1][1]
    assert [row["gate_name"] for row in gate_rows] == list(DECISION_GATE_ORDER)
    first_actual = cast(dict[str, object], gate_rows[0]["actual_value"])
    assert first_actual["contract_version"] == "research-decision-gate.v1"
    assert first_actual["source_date"] == "2026-01-02"
    _, parameters = writer.rpc_calls[0]
    run = cast(dict[str, object], parameters["p_run"])
    source_dates = cast(dict[str, object], run["source_dates"])
    assert source_dates["decision_gate_count"] == 8
    assert source_dates["snapshot_sha256"] == first_actual["attachment_snapshot_sha256"]
    stock = cast(list[dict[str, object]], parameters["p_stock_predictions"])[0]
    assert "REQUIRED_DECISION_POLICY_DATA_MISSING" not in cast(list[object], stock["reason_codes"])


def test_gate_attachment_verification_respects_database_numeric_scales() -> None:
    writer = _DatabaseRoundedWriter()
    payload = _payload(include_gates=True)
    prediction = cast(list[dict[str, object]], payload["predictions"])[0]
    prediction["calibrated_p_up"] = 0.600000004
    prediction["calibrated_p_neutral"] = 0.299999996
    payload["snapshot_sha256"] = sha256(
        json.dumps(
            {key: value for key, value in payload.items() if key != "snapshot_sha256"},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    result = TwseResearchPredictionSupabasePublisher(
        writer,
        target_environment="staging",
        publish_enabled=True,
    ).publish(payload)

    assert result.decision_gate_count == 8


def test_gate_attachment_verification_rejects_material_database_difference() -> None:
    writer = _DatabaseRoundedWriter(stored_p_up="0.60010000")

    with pytest.raises(
        ValueError,
        match=r"research gate inputs differ from stored prediction: 2330.calibrated_p_up",
    ):
        _ = TwseResearchPredictionSupabasePublisher(
            writer,
            target_environment="staging",
            publish_enabled=True,
        ).publish(_payload(include_gates=True))


def test_same_cost_profile_version_reuses_only_exact_immutable_parameters() -> None:
    writer = _Writer()
    publisher = TwseResearchPredictionSupabasePublisher(
        writer,
        target_environment="staging",
        publish_enabled=True,
    )
    first = _payload()
    _ = publisher.publish(first)

    second = _payload()
    second["reason_codes"] = ["TWSE_PRICE_ONLY_RESEARCH", "SECOND_SNAPSHOT"]
    second["snapshot_sha256"] = sha256(
        json.dumps(
            {key: value for key, value in second.items() if key != "snapshot_sha256"},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    _ = publisher.publish(second)

    assert len(writer.rpc_calls) == 2
    assert writer.cost_profiles["cost-v1"]["parameters"] == {}


def test_legacy_snapshot_metadata_does_not_change_cost_profile_identity() -> None:
    writer = _Writer()
    publisher = TwseResearchPredictionSupabasePublisher(
        writer,
        target_environment="staging",
        publish_enabled=True,
    )
    _ = publisher.publish(_payload())
    writer.cost_profiles["cost-v1"]["parameters"] = {"research_snapshot_sha256": "a" * 64}

    _ = publisher.publish(_payload())

    assert len(writer.rpc_calls) == 2
    assert writer.cost_profiles["cost-v1"]["parameters"] == {"research_snapshot_sha256": "a" * 64}


def test_cost_profile_parameter_mismatch_fails_closed_before_snapshot_rpc() -> None:
    writer = _Writer()
    publisher = TwseResearchPredictionSupabasePublisher(
        writer,
        target_environment="staging",
        publish_enabled=True,
    )
    _ = publisher.publish(_payload())
    writer.rpc_calls.clear()
    writer.cost_profiles["cost-v1"]["commission_rate"] = 0.001

    with pytest.raises(
        ValueError,
        match="different immutable parameters: commission_rate",
    ):
        _ = publisher.publish(_payload())

    assert writer.rpc_calls == []
    assert writer.cost_profiles["cost-v1"]["commission_rate"] == 0.001


def test_cost_profile_insert_without_verified_read_back_fails_closed() -> None:
    writer = _Writer(persist_cost_profiles=False)

    with pytest.raises(ValueError, match="did not return one row"):
        _ = TwseResearchPredictionSupabasePublisher(
            writer,
            target_environment="staging",
            publish_enabled=True,
        ).publish(_payload())

    assert writer.rpc_calls == []


@pytest.mark.parametrize("environment", ["", "prod"])
def test_publish_gate_rejects_unknown_environment(environment: str) -> None:
    with pytest.raises(ValueError, match="recognized environment"):
        _ = TwseResearchPredictionSupabasePublisher(
            _Writer(),
            target_environment=environment,
            publish_enabled=True,
        )


def test_production_publish_requires_a_second_explicit_gate() -> None:
    with pytest.raises(ValueError, match="PRODUCTION_PUBLISH_ENABLED"):
        _ = TwseResearchPredictionSupabasePublisher(
            _Writer(),
            target_environment="production",
            publish_enabled=True,
        )


def test_explicit_production_research_publish_remains_fail_closed() -> None:
    writer = _Writer()
    result = TwseResearchPredictionSupabasePublisher(
        writer,
        target_environment="production",
        publish_enabled=True,
        production_publish_enabled=True,
    ).publish(_payload())

    assert result.target_environment == "production"
    _, parameters = writer.rpc_calls[0]
    run = cast(dict[str, object], parameters["p_run"])
    stock = cast(list[dict[str, object]], parameters["p_stock_predictions"])[0]
    assert run["system_validation_status"] == "RESEARCH_ONLY"
    assert run["candidate_count"] == 0
    assert run["no_trade_count"] == 0
    assert run["policy_input_missing_count"] == 1
    assert stock["decision"] is None
    assert stock["decision_policy_status"] == "MISSING_REQUIRED_DATA"


def test_publish_gate_is_disabled_by_default() -> None:
    with pytest.raises(ValueError, match="PUBLISH_ENABLED"):
        _ = TwseResearchPredictionSupabasePublisher(
            _Writer(),
            target_environment="staging",
            publish_enabled=False,
        )


@pytest.mark.parametrize(
    ("scope", "version_part"),
    [
        ("OUT_OF_SAMPLE_TEST", "oos-research"),
        ("DAILY_RESEARCH_INFERENCE", "daily-research"),
        ("RETROSPECTIVE_RESEARCH_INFERENCE", "retrospective-research"),
    ],
)
def test_supported_scopes_use_semantic_bundle_identity(scope: str, version_part: str) -> None:
    writer = _Writer()
    bundle_hash = "c" * 64
    payload = _payload(
        evaluation_scope=scope,
        model_bundle_sha256=bundle_hash,
    )

    _ = TwseResearchPredictionSupabasePublisher(
        writer,
        target_environment="staging",
        publish_enabled=True,
    ).publish(payload)

    _, parameters = writer.rpc_calls[0]
    run = cast(dict[str, object], parameters["p_run"])
    assert run["model_bundle_version"] == (
        f"twse-price-research-h5-v1:{version_part}:{bundle_hash}"
    )
    assert cast(dict[str, object], run["source_dates"])["prediction_scope"] == scope
    assert str(payload["snapshot_sha256"]) not in str(run["model_bundle_version"])


def test_invalid_snapshot_is_rejected_before_any_database_write() -> None:
    writer = _Writer()
    payload = _payload()
    cast(list[dict[str, object]], payload["predictions"])[0]["decision_date"] = "2026-01-03"
    payload["snapshot_sha256"] = sha256(
        json.dumps(
            {key: value for key, value in payload.items() if key != "snapshot_sha256"},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(ValueError, match="does not match"):
        _ = TwseResearchPredictionSupabasePublisher(
            writer,
            target_environment="staging",
            publish_enabled=True,
        ).publish(payload)

    assert writer.upserts == []
    assert writer.rpc_calls == []


def test_partial_research_gate_set_is_rejected_before_database_write() -> None:
    writer = _Writer()
    payload = _payload(include_gates=True)
    prediction = cast(list[dict[str, object]], payload["predictions"])[0]
    cast(list[object], prediction["gates"]).pop()
    payload["snapshot_sha256"] = sha256(
        json.dumps(
            {key: value for key, value in payload.items() if key != "snapshot_sha256"},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(ValueError, match="all eight gates"):
        _ = TwseResearchPredictionSupabasePublisher(
            writer,
            target_environment="staging",
            publish_enabled=True,
        ).publish(payload)

    assert writer.upserts == []
    assert writer.rpc_calls == []


def test_publisher_rejects_an_unexpected_atomic_rpc_count() -> None:
    class _WrongCountWriter(_Writer):
        @override
        def rpc(
            self,
            function_name: str,
            parameters: Mapping[str, object],
        ) -> object:
            self.rpc_calls.append((function_name, dict(parameters)))
            return {"prediction_run_id": 7, "prediction_count": 0}

    with pytest.raises(ValueError, match="unexpected row count"):
        _ = TwseResearchPredictionSupabasePublisher(
            _WrongCountWriter(),
            target_environment="staging",
            publish_enabled=True,
        ).publish(_payload())


def test_tpex_publisher_writes_only_market_scoped_rows() -> None:
    writer = _TpexWriter()

    result = TpexResearchPredictionSupabasePublisher(
        writer,
        target_environment="staging",
        publish_enabled=True,
    ).publish(_tpex_payload())

    assert result.prediction_count == 1
    _, parameters = writer.rpc_calls[0]
    run = cast(dict[str, object], parameters["p_run"])
    predictions = cast(list[dict[str, object]], parameters["p_stock_predictions"])
    assert run["market_scope"] == "TPEX"
    assert run["benchmark_versions"] == {"TPEX": "benchmark-v1"}
    assert predictions[0]["market"] == "TPEX"


def test_tpex_publisher_rejects_twse_snapshot_before_database_access() -> None:
    writer = _TpexWriter()

    with pytest.raises(ValueError, match="does not match its publisher"):
        _ = TpexResearchPredictionSupabasePublisher(
            writer,
            target_environment="staging",
            publish_enabled=True,
        ).publish(_payload())

    assert writer.upserts == []
    assert writer.rpc_calls == []


def test_tpex_publisher_does_not_resolve_same_symbol_from_twse() -> None:
    writer = _Writer()

    with pytest.raises(ValueError, match="securities are unresolved"):
        _ = TpexResearchPredictionSupabasePublisher(
            writer,
            target_environment="staging",
            publish_enabled=True,
        ).publish(_tpex_payload())

    assert writer.upserts == []
    assert writer.rpc_calls == []


def test_tpex_snapshot_rejects_mixed_prediction_market_before_database_access() -> None:
    writer = _TpexWriter()
    payload = _tpex_payload()
    cast(list[dict[str, object]], payload["predictions"])[0]["market"] = "TWSE"
    payload["snapshot_sha256"] = sha256(
        json.dumps(
            {key: value for key, value in payload.items() if key != "snapshot_sha256"},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(ValueError, match="does not match the snapshot"):
        _ = TpexResearchPredictionSupabasePublisher(
            writer,
            target_environment="staging",
            publish_enabled=True,
        ).publish(payload)

    assert writer.upserts == []
    assert writer.rpc_calls == []


def test_tpex_publisher_requires_the_second_production_gate() -> None:
    with pytest.raises(ValueError, match="PRODUCTION_PUBLISH_ENABLED"):
        _ = TpexResearchPredictionSupabasePublisher(
            _TpexWriter(),
            target_environment="production",
            publish_enabled=True,
        )


def test_tpex_publisher_rejects_rpc_market_scope_mismatch() -> None:
    class _WrongMarketWriter(_TpexWriter):
        @override
        def rpc(
            self,
            function_name: str,
            parameters: Mapping[str, object],
        ) -> object:
            response = cast(dict[str, object], super().rpc(function_name, parameters))
            response["market_scope"] = "TWSE"
            return response

    with pytest.raises(ValueError, match="unexpected market scope"):
        _ = TpexResearchPredictionSupabasePublisher(
            _WrongMarketWriter(),
            target_environment="staging",
            publish_enabled=True,
        ).publish(_tpex_payload())
