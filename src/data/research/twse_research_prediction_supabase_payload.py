"""Validate and resolve a research snapshot before its single database write."""

from __future__ import annotations

# pyright: reportAny=false, reportExplicitAny=false, reportUnknownArgumentType=false
# pyright: reportUnknownVariableType=false

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
import re
from typing import cast

from src.core.research_prediction_contract import (
    research_prediction_contract_version,
)
from src.data.research.twse_research_prediction_value_validation import (
    validate_prediction_numbers,
)
from src.data.research.twse_research_decision_gate_payload import (
    GATE_ENVELOPE_VERSION,
    resolve_gate_rows,
)


RESEARCH_EVALUATION_SCOPES = frozenset(
    {
        "OUT_OF_SAMPLE_TEST",
        "DAILY_RESEARCH_INFERENCE",
        "RETROSPECTIVE_RESEARCH_INFERENCE",
    }
)
_SCOPE_VERSION_PARTS = {
    "OUT_OF_SAMPLE_TEST": "oos-research",
    "DAILY_RESEARCH_INFERENCE": "daily-research",
    "RETROSPECTIVE_RESEARCH_INFERENCE": "retrospective-research",
}
_SYMBOL_PATTERN = re.compile(r"[0-9A-Z]{2,12}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _required(payload: Mapping[str, object], name: str) -> object:
    value = payload.get(name)
    if value is None or value == "":
        raise ValueError(f"research prediction artifact is missing {name}")
    return value


def _aware_datetime(value: object, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(
            f"research prediction {name} must be an ISO datetime"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"research prediction {name} must include a timezone")
    return parsed


def _date(value: object, name: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"research prediction {name} must be an ISO date") from error


def _verify_snapshot_hash(payload: Mapping[str, object]) -> str:
    expected = str(_required(payload, "snapshot_sha256"))
    if _SHA256_PATTERN.fullmatch(expected) is None:
        raise ValueError(
            "research prediction snapshot_sha256 must be lowercase SHA-256"
        )
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


def _model_bundle_version(payload: Mapping[str, object], scope: str) -> str:
    model_version = str(_required(payload, "model_version"))
    bundle_hash_value = payload.get("model_bundle_sha256")
    if bundle_hash_value is None:
        metadata = payload.get("model_metadata")
        if isinstance(metadata, Mapping):
            bundle_hash_value = cast(Mapping[str, object], metadata).get(
                "model_bundle_sha256"
            )
    if bundle_hash_value is None or bundle_hash_value == "":
        return f"{model_version}:{_SCOPE_VERSION_PARTS[scope]}"
    bundle_hash = str(bundle_hash_value)
    if _SHA256_PATTERN.fullmatch(bundle_hash) is None:
        raise ValueError("model_bundle_sha256 must be a lowercase SHA-256")
    return f"{model_version}:{_SCOPE_VERSION_PARTS[scope]}:{bundle_hash}"


def _feature_snapshot(payload: Mapping[str, object]) -> str:
    for name in (
        "feature_snapshot_id",
        "feature_artifact_sha256",
        "input_artifact_sha256",
        "dataset_snapshot_id",
    ):
        value = payload.get(name)
        if value is not None and value != "":
            return str(value)
    raise ValueError("research prediction artifact is missing feature snapshot")


@dataclass(frozen=True)
class ParsedResearchSnapshot:
    payload: Mapping[str, object]
    predictions: tuple[Mapping[str, object], ...]
    snapshot_sha256: str
    evaluation_scope: str
    model_bundle_version: str
    feature_snapshot: str
    market: str


@dataclass(frozen=True)
class ResolvedResearchSnapshot:
    run: Mapping[str, object]
    stock_predictions: tuple[Mapping[str, object], ...]
    decision_gates: tuple[Mapping[str, object], ...]


def parse_research_snapshot(
    payload: Mapping[str, object],
) -> ParsedResearchSnapshot:
    snapshot_hash = _verify_snapshot_hash(payload)
    supplied_market = payload.get("market")
    market = "TWSE" if supplied_market is None else str(supplied_market).strip().upper()
    if market not in {"TWSE", "TPEX"}:
        raise ValueError("research prediction market is unsupported")
    if market == "TPEX" and supplied_market != "TPEX":
        raise ValueError("TPEX research snapshots require an explicit market")
    if payload.get("artifact_contract_version") != research_prediction_contract_version(
        market
    ):
        raise ValueError("unsupported research prediction artifact version")
    if payload.get("system_status") != "RESEARCH_ONLY":
        raise ValueError("only RESEARCH_ONLY snapshots can use this publisher")
    if payload.get("horizon") != 5:
        raise ValueError("UNSUPPORTED_HORIZON")
    for name in ("model_metadata", "cost_metadata", "validation"):
        if not isinstance(payload.get(name), Mapping):
            raise ValueError(f"research prediction {name} must be an object")

    raw_predictions = payload.get("predictions")
    if not isinstance(raw_predictions, list) or not raw_predictions:
        raise ValueError("research prediction artifact has no predictions")
    predictions = tuple(
        cast(Mapping[str, object], value)
        for value in raw_predictions
        if isinstance(value, Mapping)
    )
    if len(predictions) != len(raw_predictions):
        raise ValueError("research prediction rows must be JSON objects")

    snapshot_date = _date(_required(payload, "as_of_date"), "as_of_date")
    decision_at = _aware_datetime(_required(payload, "decision_at"), "decision_at")
    training_end = _date(_required(payload, "training_end_date"), "training_end_date")
    if training_end >= snapshot_date:
        raise ValueError("training_end_date must precede the research as_of_date")
    if decision_at.date() != snapshot_date:
        raise ValueError("decision_at date must match the research as_of_date")

    scopes: set[str] = set()
    symbols: set[str] = set()
    ranks: set[int] = set()
    for prediction in predictions:
        scope = str(_required(prediction, "evaluation_scope"))
        scopes.add(scope)
        symbol = str(_required(prediction, "symbol"))
        if _SYMBOL_PATTERN.fullmatch(symbol) is None or symbol in symbols:
            raise ValueError("research prediction symbols must be unique and safe")
        symbols.add(symbol)
        global_rank_value = _required(prediction, "global_rank")
        if isinstance(global_rank_value, bool) or not isinstance(
            global_rank_value, int
        ):
            raise ValueError("research prediction global_rank must be an integer")
        global_rank = global_rank_value
        if global_rank < 1 or global_rank in ranks:
            raise ValueError(
                "research prediction global ranks must be unique and positive"
            )
        ranks.add(global_rank)
        if (
            prediction.get("horizon") != 5
            or prediction.get("market") != market
            or prediction.get("decision_date") != snapshot_date.isoformat()
            or prediction.get("decision_at") != str(_required(payload, "decision_at"))
            or prediction.get("data_quality_status") not in {"PASS", "WARN"}
        ):
            raise ValueError("research prediction row does not match the snapshot")
        latest_available_at = _aware_datetime(
            _required(prediction, "latest_available_at"), "latest_available_at"
        )
        if latest_available_at > decision_at:
            raise ValueError("latest_available_at cannot exceed decision_at")
        reasons = prediction.get("reason_codes")
        if (
            not isinstance(reasons, list)
            or not reasons
            or any(not value for value in reasons)
        ):
            raise ValueError(
                "research prediction reason_codes must be a non-empty array"
            )
        validate_prediction_numbers(prediction)

    if len(scopes) != 1:
        raise ValueError("one research snapshot cannot mix evaluation scopes")
    scope = next(iter(scopes))
    if scope not in RESEARCH_EVALUATION_SCOPES:
        raise ValueError("research prediction evaluation_scope is unsupported")
    return ParsedResearchSnapshot(
        payload=payload,
        predictions=predictions,
        snapshot_sha256=snapshot_hash,
        evaluation_scope=scope,
        model_bundle_version=_model_bundle_version(payload, scope),
        feature_snapshot=_feature_snapshot(payload),
        market=market,
    )


def resolve_research_snapshot(
    parsed: ParsedResearchSnapshot,
    security_ids: Mapping[str, int],
) -> ResolvedResearchSnapshot:
    payload = parsed.payload
    latest_available_at = max(
        _aware_datetime(_required(value, "latest_available_at"), "latest_available_at")
        for value in parsed.predictions
    ).isoformat()
    rows = tuple(
        _stock_row(prediction, security_ids, market=parsed.market)
        for prediction in parsed.predictions
    )
    gates = resolve_gate_rows(
        parsed.predictions,
        security_ids,
        snapshot_sha256=parsed.snapshot_sha256,
        snapshot_date=_date(_required(payload, "as_of_date"), "as_of_date"),
    )
    run = {
        "as_of_date": _required(payload, "as_of_date"),
        "decision_at": _required(payload, "decision_at"),
        "horizon": 5,
        "market_scope": parsed.market,
        "model_bundle_version": parsed.model_bundle_version,
        "feature_schema_hash": _required(payload, "feature_schema_hash"),
        "benchmark_versions": {parsed.market: _required(payload, "benchmark_version")},
        "cost_profile_version": _required(payload, "cost_profile_version"),
        "training_end_date": _required(payload, "training_end_date"),
        "system_validation_status": "RESEARCH_ONLY",
        "source_dates": {
            "prediction_scope": parsed.evaluation_scope,
            "feature_snapshot": parsed.feature_snapshot,
            "snapshot_sha256": parsed.snapshot_sha256,
            "decision_gate_count": len(gates),
            "decision_gate_attachment_contract": GATE_ENVELOPE_VERSION,
        },
        "latest_available_at": latest_available_at,
        "candidate_count": 0,
        "watch_count": 0,
        "no_trade_count": len(parsed.predictions),
        "hard_fail_count": 0,
    }
    return ResolvedResearchSnapshot(
        run=run,
        stock_predictions=rows,
        decision_gates=gates,
    )


def _stock_row(
    prediction: Mapping[str, object],
    security_ids: Mapping[str, int],
    *,
    market: str,
) -> Mapping[str, object]:
    symbol = str(_required(prediction, "symbol"))
    original_quality = str(_required(prediction, "data_quality_status"))
    reasons = cast(list[object], prediction["reason_codes"])
    reason_codes = [str(value) for value in reasons]
    reason_codes.append("RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY")
    if original_quality == "WARN":
        reason_codes.append("RESEARCH_DATA_QUALITY_WARN")
    return {
        "security_id": security_ids[symbol],
        "market": market,
        "industry": prediction.get("industry"),
        "model_raw_score": _required(prediction, "model_raw_score"),
        "rank_score": _required(prediction, "rank_score"),
        "global_rank": _required(prediction, "global_rank"),
        "global_rank_percentile": _required(prediction, "global_rank_percentile"),
        "industry_rank": prediction.get("industry_rank"),
        "industry_rank_percentile": prediction.get("industry_rank_percentile"),
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
        "forecast_volatility": prediction.get("forecast_volatility"),
        "downside_risk": prediction.get("downside_risk"),
        "adv20_ntd": prediction.get("adv20_ntd"),
        "maximum_order_notional_ntd": prediction.get("maximum_order_notional_ntd"),
        "market_regime": prediction.get("market_regime"),
        "market_exposure_cap": prediction.get("market_exposure_cap"),
        "estimated_round_trip_cost": _required(prediction, "estimated_round_trip_cost"),
        "data_quality_status": "PASS" if original_quality == "PASS" else "FAIL",
        "decision": "NO_TRADE",
        "reason_codes": list(dict.fromkeys(reason_codes)),
    }


__all__ = [
    "ParsedResearchSnapshot",
    "RESEARCH_EVALUATION_SCOPES",
    "ResolvedResearchSnapshot",
    "parse_research_snapshot",
    "resolve_research_snapshot",
]
