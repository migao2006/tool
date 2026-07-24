import type {
  DataQualityAuditRow,
  Decision,
  DecisionGateRow,
  DecisionPolicyStatus,
  JsonRecord,
  JsonValue,
  MarketPredictionRow,
  MarketScope,
  PredictionRunRow,
  SecurityHistoryRow,
  SecurityRow,
  SnapshotRows,
  StockPredictionRow,
} from "./types.ts";
import {
  CURRENT_INDUSTRY_CLASSIFICATION_BASIS,
  resolveCurrentIndustryName,
} from "./industry-classifications.ts";

const RESEARCH_DATA_QUALITY_WARNING = "RESEARCH_DATA_QUALITY_WARN";
const LEGACY_NO_POLICY_REASON = "RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY";
const REQUIRED_POLICY_DATA_MISSING = "REQUIRED_DECISION_POLICY_DATA_MISSING";
const RESEARCH_GATE_ENVELOPE_VERSIONS = new Set([
  "research-decision-gate.v1",
  "research-decision-gate.v2",
]);
const DECISIONS = new Set<Decision>(["CANDIDATE", "WATCH", "NO_TRADE"]);
const POLICY_STATUSES = new Set<DecisionPolicyStatus>([
  "EVALUATED",
  "MISSING_REQUIRED_DATA",
  "VALIDATION_FAILED",
  "HARD_FAIL",
]);
const COST_PROFILES = new Set([
  "low_cost",
  "base_cost",
  "stressed_cost",
  "extreme_cost",
]);

export interface PublicDataQuality {
  status: "PASS" | "WARN" | "HARD_FAIL";
  hardFail: boolean;
}

export function resolvePublicDataQuality(
  run: PredictionRunRow,
  prediction: StockPredictionRow,
  audit: DataQualityAuditRow | undefined,
): PublicDataQuality {
  if (audit) {
    if (audit.hard_fail) return { status: "HARD_FAIL", hardFail: true };
    return audit.quality_status === "FAIL"
      ? { status: "WARN", hardFail: false }
      : { status: "PASS", hardFail: false };
  }

  if (prediction.data_quality_status === "HARD_FAIL") {
    return { status: "HARD_FAIL", hardFail: true };
  }
  if (prediction.data_quality_status === "WARN") {
    return { status: "WARN", hardFail: false };
  }
  const researchWarning = run.system_validation_status === "RESEARCH_ONLY" &&
    prediction.data_quality_status === "FAIL" &&
    prediction.reason_codes.includes(RESEARCH_DATA_QUALITY_WARNING);
  if (researchWarning) return { status: "WARN", hardFail: false };
  return prediction.data_quality_status === "FAIL"
    ? { status: "HARD_FAIL", hardFail: true }
    : { status: "PASS", hardFail: false };
}

export interface PublicDecisionPolicy {
  decision: Decision | null;
  status: DecisionPolicyStatus;
}

function isMissingPolicyReason(reason: string): boolean {
  return reason === LEGACY_NO_POLICY_REASON ||
    reason === REQUIRED_POLICY_DATA_MISSING ||
    reason.endsWith("_INPUT_MISSING") ||
    reason.includes("SOURCE_DATE_MISSING");
}

export function resolvePublicDecisionPolicy(
  run: PredictionRunRow,
  prediction: StockPredictionRow,
  quality: PublicDataQuality,
  gates: JsonRecord[],
): PublicDecisionPolicy {
  if (quality.hardFail) return { decision: null, status: "HARD_FAIL" };

  const suppliedStatus = prediction.decision_policy_status ?? null;
  if (suppliedStatus !== null && !POLICY_STATUSES.has(suppliedStatus)) {
    return { decision: null, status: "VALIDATION_FAILED" };
  }
  if (suppliedStatus !== null) {
    if (
      suppliedStatus === "EVALUATED" &&
      prediction.decision !== null &&
      DECISIONS.has(prediction.decision)
    ) {
      return { decision: prediction.decision, status: suppliedStatus };
    }
    if (
      suppliedStatus !== "EVALUATED" &&
      prediction.decision === null
    ) {
      return { decision: null, status: suppliedStatus };
    }
    return { decision: null, status: "VALIDATION_FAILED" };
  }

  const gateReasons = gates.map((gate) =>
    typeof gate.reason_code === "string" ? gate.reason_code : ""
  );
  if (
    prediction.reason_codes.some(isMissingPolicyReason) ||
    gateReasons.some(isMissingPolicyReason)
  ) {
    return { decision: null, status: "MISSING_REQUIRED_DATA" };
  }
  if (run.system_validation_status === "RESEARCH_ONLY") {
    return { decision: null, status: "VALIDATION_FAILED" };
  }
  if (prediction.decision !== null && DECISIONS.has(prediction.decision)) {
    return { decision: prediction.decision, status: "EVALUATED" };
  }
  return { decision: null, status: "VALIDATION_FAILED" };
}

function numberValue(value: JsonValue): number | null {
  if (value === null || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function costProfileName(version: string): string | null {
  const profile = version.split(":").at(-1) ?? "";
  return COST_PROFILES.has(profile) ? profile : null;
}

export function marketName(value: "TWSE" | "TPEX"): "LISTED" | "OTC" {
  return value === "TWSE" ? "LISTED" : "OTC";
}

export function mapMarket(
  run: PredictionRunRow,
  markets: MarketPredictionRow[],
  marketScope: MarketScope,
): JsonRecord | null {
  const market = markets.find((row) => row.market === marketScope);
  if (!market) return null;
  return {
    as_of_date: run.as_of_date,
    decision_at: run.decision_at,
    horizon: run.horizon,
    p_up: numberValue(market.calibrated_p_up),
    p_neutral: numberValue(market.calibrated_p_neutral),
    p_down: numberValue(market.calibrated_p_down),
    market_regime: market.market_regime,
    forecast_market_volatility: numberValue(market.forecast_market_volatility),
    market_exposure_cap: numberValue(market.market_exposure_cap),
    model_version: market.model_version,
    training_end_date: market.training_end_date,
  };
}

function unwrapGateActual(value: JsonValue): {
  actual: JsonValue;
  sourceDate: string | null;
  evidence: JsonValue;
} {
  if (
    value !== null && typeof value === "object" && !Array.isArray(value) &&
    typeof value.contract_version === "string" &&
    RESEARCH_GATE_ENVELOPE_VERSIONS.has(value.contract_version) &&
    Object.hasOwn(value, "value")
  ) {
    return {
      actual: value.value,
      sourceDate: typeof value.source_date === "string"
        ? value.source_date
        : null,
      evidence: Object.hasOwn(value, "evidence") ? value.evidence : null,
    };
  }
  return { actual: value, sourceDate: null, evidence: null };
}

function mapGates(rows: DecisionGateRow[]): JsonRecord[] {
  return [...rows].sort((left, right) => left.gate_order - right.gate_order)
    .map((row) => {
      const envelope = unwrapGateActual(row.actual_value);
      return {
        gate: row.gate_name,
        passed: row.passed,
        actual: envelope.actual,
        threshold: row.threshold_value,
        reason_code: row.reason_code,
        source_date: envelope.sourceDate,
        evidence: envelope.evidence,
      };
    });
}

function positionLimit(
  gates: JsonRecord[],
  field: "maximum_single_name_weight" | "maximum_industry_weight",
): number | null {
  const gate = gates.find((value) => value.gate === "position_capacity_limits");
  const evidence = gate?.evidence;
  if (
    evidence === null || typeof evidence !== "object" ||
    Array.isArray(evidence)
  ) return null;
  if (
    evidence.contract_version !== "decision-policy-required-evidence.v1" ||
    evidence.category !== "POSITION_LIMITS" ||
    evidence.status !== "AVAILABLE" ||
    evidence.validation_result !== "PASS" ||
    evidence.reason_code !== "PASS"
  ) return null;
  const details = evidence.details;
  if (
    details === null || typeof details !== "object" || Array.isArray(details)
  ) return null;
  return numberValue(details[field]);
}

export function mapPrediction(
  run: PredictionRunRow,
  prediction: StockPredictionRow,
  security: SecurityRow,
  currentHistory: SecurityHistoryRow | undefined,
  audit: DataQualityAuditRow | undefined,
  gates: DecisionGateRow[],
): JsonRecord {
  const quality = resolvePublicDataQuality(run, prediction, audit);
  const mappedGates = mapGates(gates);
  const policy = resolvePublicDecisionPolicy(
    run,
    prediction,
    quality,
    mappedGates,
  );
  const predictionReasons = mappedGates.length > 0
    ? prediction.reason_codes.filter((reason) =>
      reason !== LEGACY_NO_POLICY_REASON
    )
    : prediction.reason_codes;
  return {
    as_of_date: run.as_of_date,
    decision_at: run.decision_at,
    symbol: security.symbol,
    name: security.display_name,
    market: marketName(prediction.market),
    industry: prediction.industry,
    current_industry: currentHistory
      ? resolveCurrentIndustryName(
        security.market,
        currentHistory.industry_code,
        currentHistory.industry_name,
      )
      : null,
    current_industry_code: currentHistory?.industry_code ?? null,
    industry_classification_effective_from: currentHistory?.effective_from ??
      null,
    industry_classification_effective_to: currentHistory?.effective_to ?? null,
    industry_classification_available_at: currentHistory?.available_at ?? null,
    industry_classification_basis: currentHistory
      ? CURRENT_INDUSTRY_CLASSIFICATION_BASIS
      : null,
    asset_type: "STOCK",
    horizon: run.horizon,
    rank_score: numberValue(prediction.rank_score),
    global_rank: prediction.global_rank,
    global_rank_percentile: numberValue(prediction.global_rank_percentile),
    industry_rank: prediction.industry_rank,
    industry_rank_percentile: numberValue(prediction.industry_rank_percentile),
    calibrated_p_up: numberValue(prediction.calibrated_p_up),
    calibrated_p_neutral: numberValue(prediction.calibrated_p_neutral),
    calibrated_p_down: numberValue(prediction.calibrated_p_down),
    calibration_version: prediction.calibration_version,
    gross_q10: numberValue(prediction.gross_q10),
    gross_q50: numberValue(prediction.gross_q50),
    gross_q90: numberValue(prediction.gross_q90),
    net_q10: numberValue(prediction.net_q10),
    net_q50: numberValue(prediction.net_q50),
    net_q90: numberValue(prediction.net_q90),
    interval_width: numberValue(prediction.interval_width),
    calibration_status: prediction.calibration_status,
    forecast_volatility: numberValue(prediction.forecast_volatility),
    downside_risk: numberValue(prediction.downside_risk),
    market_regime: prediction.market_regime,
    market_exposure_cap: numberValue(prediction.market_exposure_cap),
    estimated_round_trip_cost: numberValue(
      prediction.estimated_round_trip_cost,
    ),
    data_quality_status: quality.status,
    data_quality_hard_fail: quality.hardFail,
    decision: policy.decision,
    decision_policy_status: policy.status,
    reason_codes: [
      ...new Set([
        ...predictionReasons,
        ...(audit?.reason_codes ?? []),
      ]),
    ],
    model_version: run.model_bundle_version,
    feature_schema_hash: run.feature_schema_hash,
    cost_profile_version: run.cost_profile_version,
    training_end_date: run.training_end_date,
    source_dates: audit?.source_dates ?? run.source_dates,
    latest_available_at: audit?.latest_available_at ?? run.latest_available_at,
    liquidity_bucket: null,
    adv20: numberValue(prediction.adv20_ntd),
    max_order_notional_ntd: numberValue(prediction.maximum_order_notional_ntd),
    max_single_position: positionLimit(
      mappedGates,
      "maximum_single_name_weight",
    ),
    max_industry_position: positionLimit(
      mappedGates,
      "maximum_industry_weight",
    ),
    cost_profile: costProfileName(run.cost_profile_version),
    previous_global_rank: null,
    previous_decision: null,
    gates: mappedGates,
  };
}

export function mapValidation(rows: SnapshotRows): JsonRecord {
  const validation = rows.validationRun;
  if (!validation) return {};
  return {
    validation_status: validation.validation_status,
    validation_run_id: validation.validation_run_id,
    locked_holdout: validation.locked_holdout,
    frozen_config_hash: validation.frozen_config_hash,
    started_at: validation.started_at,
    completed_at: validation.completed_at,
    known_limitations: validation.limitations,
    fold_metrics: rows.validationMetrics.map((metric) => ({
      fold_number: metric.fold_number,
      metric_name: metric.metric_name,
      metric_value: numberValue(metric.metric_value),
      metric_payload: metric.metric_payload,
    })),
    cost_sensitivity: rows.backtests.map((backtest) => ({
      cost_scenario: backtest.cost_scenario,
      cost_multiplier: numberValue(backtest.cost_multiplier),
      status: backtest.status,
      summary_metrics: backtest.summary_metrics,
      completed_at: backtest.completed_at,
    })),
  };
}
