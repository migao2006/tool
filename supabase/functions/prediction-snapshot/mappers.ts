import type {
  DataQualityAuditRow,
  DecisionGateRow,
  JsonRecord,
  JsonValue,
  MarketPredictionRow,
  MarketScope,
  PredictionRunRow,
  SecurityRow,
  SnapshotRows,
  StockPredictionRow,
} from "./types.ts";

const RESEARCH_DATA_QUALITY_WARNING = "RESEARCH_DATA_QUALITY_WARN";
const LEGACY_NO_POLICY_REASON = "RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY";
const RESEARCH_GATE_ENVELOPE_VERSION = "research-decision-gate.v1";

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

  const researchWarning = run.system_validation_status === "RESEARCH_ONLY" &&
    prediction.data_quality_status === "FAIL" &&
    prediction.reason_codes.includes(RESEARCH_DATA_QUALITY_WARNING);
  if (researchWarning) return { status: "WARN", hardFail: false };
  return prediction.data_quality_status === "FAIL"
    ? { status: "HARD_FAIL", hardFail: true }
    : { status: "PASS", hardFail: false };
}

function numberValue(value: JsonValue): number | null {
  if (value === null || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
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
} {
  if (
    value !== null && typeof value === "object" && !Array.isArray(value) &&
    value.contract_version === RESEARCH_GATE_ENVELOPE_VERSION &&
    Object.hasOwn(value, "value")
  ) {
    return {
      actual: value.value,
      sourceDate: typeof value.source_date === "string"
        ? value.source_date
        : null,
    };
  }
  return { actual: value, sourceDate: null };
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
      };
    });
}

export function mapPrediction(
  run: PredictionRunRow,
  prediction: StockPredictionRow,
  security: SecurityRow,
  audit: DataQualityAuditRow | undefined,
  gates: DecisionGateRow[],
): JsonRecord {
  const quality = resolvePublicDataQuality(run, prediction, audit);
  const mappedGates = mapGates(gates);
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
    decision: prediction.decision,
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
    max_single_position: null,
    max_industry_position: null,
    cost_profile: null,
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
