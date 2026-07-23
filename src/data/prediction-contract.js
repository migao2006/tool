import { CURRENT_HORIZON, SYSTEM_STATUS, normalizeHorizon } from "../core/five-day-contract.js";
import {
  DEFAULT_MARKET_SCOPE,
  createStockKey,
  normalizeMarketScope,
} from "../core/market-scope.js";
import { validateFormalSnapshot } from "./prediction-validator.js?v=api-5";

const DECISIONS = new Set(["CANDIDATE", "WATCH", "NO_TRADE"]);
const SYSTEM_STATUSES = new Set(Object.values(SYSTEM_STATUS));
const API_CONTRACT_VERSION = "prediction-snapshot.v1";

function firstValue(source, keys, fallback = null) {
  for (const key of keys) {
    if (source?.[key] !== undefined && source[key] !== null) return source[key];
  }
  return fallback;
}

function nullableNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function nullableString(value) {
  if (value === null || value === undefined || value === "") return null;
  return String(value);
}

function stringList(value) {
  if (!Array.isArray(value)) return [];
  return value.filter((item) => item !== null && item !== undefined).map(String);
}

function normalizeMarket(value) {
  const market = String(value ?? "").trim().toUpperCase();
  if (["TWSE", "LISTED", "上市"].includes(market)) return "TWSE";
  if (["TPEX", "OTC", "上櫃"].includes(market)) return "TPEX";
  return market || null;
}

function normalizeGate(gate) {
  return Object.freeze({
    key: nullableString(firstValue(gate, ["key", "gate", "name"])),
    passed: typeof gate?.passed === "boolean" ? gate.passed : null,
    actual: firstValue(gate, ["actual", "actual_value"]),
    threshold: firstValue(gate, ["threshold", "threshold_value"]),
    reason_code: nullableString(firstValue(gate, ["reason_code", "reasonCode"])),
    source_date: nullableString(firstValue(gate, ["source_date", "sourceDate"])),
  });
}

export function normalizePrediction(record, snapshotHorizon = CURRENT_HORIZON) {
  if (!record || typeof record !== "object") throw new TypeError("預測紀錄格式不正確。");
  const horizon = normalizeHorizon(firstValue(record, ["horizon"], snapshotHorizon));
  if (horizon !== CURRENT_HORIZON) throw new RangeError("目前只接受 5 個交易日模型輸出。");

  const rawDataQualityStatus = firstValue(record, ["data_quality_status", "dataQualityStatus"]);
  const dataQualityStatus = rawDataQualityStatus === null || rawDataQualityStatus === undefined
    ? null
    : String(rawDataQualityStatus).toUpperCase();
  const hardFail = Boolean(firstValue(record, ["data_quality_hard_fail", "hard_fail", "isHardFail"], false))
    || ["FAIL", "HARD_FAIL"].includes(dataQualityStatus);
  const rawDecision = firstValue(record, ["decision"]);
  const decisionValue = rawDecision === null || rawDecision === undefined ? "" : String(rawDecision).toUpperCase();
  const rawAssetType = firstValue(record, ["asset_type", "assetType"]);

  return Object.freeze({
    as_of_date: nullableString(firstValue(record, ["as_of_date", "asOfDate"])),
    decision_at: nullableString(firstValue(record, ["decision_at", "decisionAt"])),
    symbol: nullableString(firstValue(record, ["symbol", "security_id"])),
    name: nullableString(firstValue(record, ["name", "security_name"])),
    market: normalizeMarket(firstValue(record, ["market"])),
    industry: nullableString(firstValue(record, ["industry"])),
    current_industry: nullableString(firstValue(record, ["current_industry", "currentIndustry"])),
    current_industry_code: nullableString(firstValue(record, ["current_industry_code", "currentIndustryCode"])),
    industry_classification_effective_from: nullableString(firstValue(record, ["industry_classification_effective_from", "industryClassificationEffectiveFrom"])),
    industry_classification_effective_to: nullableString(firstValue(record, ["industry_classification_effective_to", "industryClassificationEffectiveTo"])),
    industry_classification_available_at: nullableString(firstValue(record, ["industry_classification_available_at", "industryClassificationAvailableAt"])),
    industry_classification_basis: nullableString(firstValue(record, ["industry_classification_basis", "industryClassificationBasis"])),
    asset_type: rawAssetType === null || rawAssetType === undefined ? null : String(rawAssetType).toUpperCase(),
    liquidity_bucket: nullableString(firstValue(record, ["liquidity_bucket", "liquidityBucket"])),
    horizon,
    rank_score: nullableNumber(firstValue(record, ["rank_score", "Rank Score", "rankScore"])),
    global_rank: nullableNumber(firstValue(record, ["global_rank", "globalRank"])),
    global_rank_percentile: nullableNumber(firstValue(record, ["global_rank_percentile", "globalRankPercentile"])),
    industry_rank: nullableNumber(firstValue(record, ["industry_rank", "industryRank"])),
    industry_rank_percentile: nullableNumber(firstValue(record, ["industry_rank_percentile", "industryRankPercentile"])),
    calibrated_p_up: nullableNumber(firstValue(record, ["calibrated_p_up", "calibratedPUp"])),
    calibrated_p_neutral: nullableNumber(firstValue(record, ["calibrated_p_neutral", "calibratedPNeutral"])),
    calibrated_p_down: nullableNumber(firstValue(record, ["calibrated_p_down", "calibratedPDown"])),
    calibration_version: nullableString(firstValue(record, ["calibration_version", "calibrationVersion"])),
    gross_q10: nullableNumber(firstValue(record, ["gross_q10", "grossQ10"])),
    gross_q50: nullableNumber(firstValue(record, ["gross_q50", "grossQ50"])),
    gross_q90: nullableNumber(firstValue(record, ["gross_q90", "grossQ90"])),
    net_q10: nullableNumber(firstValue(record, ["net_q10", "netQ10"])),
    net_q50: nullableNumber(firstValue(record, ["net_q50", "netQ50"])),
    net_q90: nullableNumber(firstValue(record, ["net_q90", "netQ90"])),
    interval_width: nullableNumber(firstValue(record, ["interval_width", "intervalWidth"])),
    calibration_status: nullableString(firstValue(record, ["calibration_status", "calibrationStatus"])),
    forecast_volatility: nullableNumber(firstValue(record, ["forecast_volatility", "forecastVolatility"])),
    downside_risk: nullableNumber(firstValue(record, ["downside_risk", "downsideRisk"])),
    market_regime: nullableString(firstValue(record, ["market_regime", "marketRegime"])),
    adv20: nullableNumber(firstValue(record, ["ADV20", "adv20"])),
    max_order_notional_ntd: nullableNumber(firstValue(record, ["max_order_notional_ntd", "maxOrderNotionalNtd"])),
    max_single_position: nullableNumber(firstValue(record, ["max_single_position", "maxSinglePosition"])),
    max_industry_position: nullableNumber(firstValue(record, ["max_industry_position", "maxIndustryPosition"])),
    market_exposure_cap: nullableNumber(firstValue(record, ["market_exposure_cap", "marketExposureCap"])),
    estimated_round_trip_cost: nullableNumber(firstValue(record, ["estimated_round_trip_cost", "estimatedRoundTripCost"])),
    cost_profile: nullableString(firstValue(record, ["cost_profile", "costProfile"])),
    cost_profile_version: nullableString(firstValue(record, ["cost_profile_version", "costProfileVersion"])),
    data_quality_status: dataQualityStatus,
    data_quality_hard_fail: hardFail,
    decision: DECISIONS.has(decisionValue) ? decisionValue : null,
    reason_codes: Object.freeze(stringList(firstValue(record, ["reason_codes", "reasonCodes"], []))),
    model_version: nullableString(firstValue(record, ["model_version", "modelVersion"])),
    feature_schema_hash: nullableString(firstValue(record, ["feature_schema_hash", "featureSchemaHash"])),
    training_end_date: nullableString(firstValue(record, ["training_end_date", "trainingEndDate"])),
    source_dates: firstValue(record, ["source_dates", "sourceDates"]),
    latest_available_at: nullableString(firstValue(record, ["latest_available_at", "latestAvailableAt"])),
    previous_global_rank: nullableNumber(firstValue(record, ["previous_global_rank", "previousGlobalRank"])),
    previous_decision: nullableString(firstValue(record, ["previous_decision", "previousDecision"])),
    gates: Object.freeze((Array.isArray(record.gates) ? record.gates : []).map(normalizeGate)),
  });
}

function normalizeMarketSnapshot(raw = {}) {
  const direction = firstValue(raw, ["market_direction", "direction"], raw);
  return Object.freeze({
    as_of_date: nullableString(firstValue(raw, ["as_of_date", "asOfDate"])),
    decision_at: nullableString(firstValue(raw, ["decision_at", "decisionAt"])),
    horizon: nullableNumber(firstValue(raw, ["horizon"])),
    p_up: nullableNumber(firstValue(direction, ["calibrated_p_up", "p_up", "up"])),
    p_neutral: nullableNumber(firstValue(direction, ["calibrated_p_neutral", "p_neutral", "neutral"])),
    p_down: nullableNumber(firstValue(direction, ["calibrated_p_down", "p_down", "down"])),
    regime: nullableString(firstValue(raw, ["market_regime", "regime"])),
    forecast_volatility: nullableNumber(firstValue(raw, ["forecast_market_volatility", "forecast_volatility"])),
    exposure_cap: nullableNumber(firstValue(raw, ["market_exposure_cap", "exposure_cap"])),
    model_version: nullableString(firstValue(raw, ["model_version", "modelVersion"])),
    training_end_date: nullableString(firstValue(raw, ["training_end_date", "trainingEndDate"])),
  });
}

function normalizeValidation(raw = {}) {
  return Object.freeze({
    walk_forward: firstValue(raw, ["walk_forward", "walkForward"]),
    locked_holdout: firstValue(raw, ["locked_holdout", "lockedHoldout"]),
    ndcg_10: nullableNumber(firstValue(raw, ["ndcg_10", "ndcg@10"])),
    ndcg_20: nullableNumber(firstValue(raw, ["ndcg_20", "ndcg@20"])),
    ndcg_50: nullableNumber(firstValue(raw, ["ndcg_50", "ndcg@50"])),
    rank_ic: nullableNumber(firstValue(raw, ["rank_ic", "rankIc"])),
    icir: nullableNumber(firstValue(raw, ["icir"])),
    probability_calibration: firstValue(raw, ["probability_calibration", "probabilityCalibration"]),
    quantile_coverage: nullableNumber(firstValue(raw, ["quantile_coverage", "quantileCoverage"])),
    cost_sensitivity: firstValue(raw, ["cost_sensitivity", "costSensitivity"]),
    baseline_comparison: firstValue(raw, ["baseline_comparison", "baselineComparison"]),
    known_limitations: Object.freeze(stringList(firstValue(raw, ["known_limitations", "knownLimitations"], []))),
  });
}

export function normalizePredictionSnapshot(
  payload,
  expectedHorizon = CURRENT_HORIZON,
  expectedMarketScope = DEFAULT_MARKET_SCOPE,
) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new TypeError("預測 API 回傳格式不正確。");
  }
  const horizon = normalizeHorizon(firstValue(payload, ["horizon"], expectedHorizon));
  if (horizon !== expectedHorizon || horizon !== CURRENT_HORIZON) {
    throw new RangeError("預測 API 回傳的 horizon 與請求不一致。");
  }
  const requestedMarketScope = normalizeMarketScope(expectedMarketScope);
  const marketScope = normalizeMarketScope(
    firstValue(payload, ["market_scope", "marketScope"], DEFAULT_MARKET_SCOPE),
  );
  if (marketScope !== requestedMarketScope) {
    throw new RangeError("預測 API 回傳的市場與請求不一致。");
  }

  const rawPredictions = firstValue(payload, ["predictions", "candidates", "stock_predictions"], []);
  const rawWatchlist = firstValue(payload, ["watchlist", "watchlist_predictions"], []);
  const predictions = (Array.isArray(rawPredictions) ? rawPredictions : []).map((record) => normalizePrediction(record, horizon));
  const watchlist = (Array.isArray(rawWatchlist) ? rawWatchlist : []).map((record) => normalizePrediction(record, horizon));
  const explicitExcluded = firstValue(payload, ["excluded", "excluded_securities"], []);
  const excluded = [
    ...(Array.isArray(explicitExcluded) ? explicitExcluded.map((record) => normalizePrediction(record, horizon)) : []),
    ...predictions.filter((record) => record.data_quality_hard_fail),
  ];
  const allRecords = [...predictions, ...watchlist, ...excluded];
  if (allRecords.some((record) => record.market !== marketScope)) {
    throw new RangeError("預測 API 回傳包含其他市場的股票資料。");
  }
  const uniqueExcluded = [
    ...new Map(excluded.map((record) => [createStockKey(record), record])).values(),
  ];
  const statusValue = String(firstValue(payload, ["system_status", "systemStatus"], SYSTEM_STATUS.RESEARCH_ONLY)).toUpperCase();
  const apiContractVersion = nullableString(firstValue(payload, ["api_contract_version", "apiContractVersion"]));
  if (apiContractVersion && apiContractVersion !== API_CONTRACT_VERSION) {
    throw new RangeError("預測 API 契約版本不受支援。");
  }

  const snapshot = Object.freeze({
    apiContractVersion,
    horizon,
    marketScope,
    systemStatus: SYSTEM_STATUSES.has(statusValue) ? statusValue : SYSTEM_STATUS.FAIL,
    asOfDate: nullableString(firstValue(payload, ["as_of_date", "asOfDate"])),
    decisionAt: nullableString(firstValue(payload, ["decision_at", "decisionAt"])),
    stale: Boolean(firstValue(payload, ["stale", "is_stale"], false)),
    dataQualityHardFail: Boolean(firstValue(payload, ["data_quality_hard_fail", "dataQualityHardFail"], false)),
    reasonCodes: Object.freeze(stringList(firstValue(payload, ["reason_codes", "reasonCodes"], []))),
    market: normalizeMarketSnapshot(firstValue(payload, ["market", "market_snapshot"], payload)),
    predictions: Object.freeze(predictions),
    candidates: Object.freeze(predictions.filter((record) => !record.data_quality_hard_fail)),
    excluded: Object.freeze(uniqueExcluded),
    watchlist: Object.freeze(watchlist),
    modelVersion: nullableString(firstValue(payload, ["model_version", "modelVersion"])),
    trainingEndDate: nullableString(firstValue(payload, ["training_end_date", "trainingEndDate"])),
    costProfileVersion: nullableString(firstValue(payload, ["cost_profile_version", "costProfileVersion"])),
    validation: normalizeValidation(firstValue(payload, ["validation", "validation_report"], {})),
  });
  validateFormalSnapshot(snapshot);
  return snapshot;
}

export function createUnavailableSnapshot({
  horizon = CURRENT_HORIZON,
  marketScope = DEFAULT_MARKET_SCOPE,
  status = SYSTEM_STATUS.RESEARCH_ONLY,
  reasonCode = "REAL_DATA_NOT_CONNECTED",
} = {}) {
  const normalizedHorizon = normalizeHorizon(horizon);
  const normalizedMarketScope = normalizeMarketScope(marketScope);
  if (normalizedHorizon !== CURRENT_HORIZON) {
    const emptyRecords = Object.freeze([]);
    const statusValue = String(status).toUpperCase();
    return Object.freeze({
      apiContractVersion: null,
      horizon: normalizedHorizon,
      marketScope: normalizedMarketScope,
      systemStatus: SYSTEM_STATUSES.has(statusValue) ? statusValue : SYSTEM_STATUS.FAIL,
      asOfDate: null,
      decisionAt: null,
      stale: false,
      dataQualityHardFail: false,
      reasonCodes: Object.freeze(["UNSUPPORTED_HORIZON"]),
      market: normalizeMarketSnapshot({ horizon: normalizedHorizon }),
      predictions: emptyRecords,
      candidates: emptyRecords,
      excluded: emptyRecords,
      watchlist: emptyRecords,
      modelVersion: null,
      trainingEndDate: null,
      costProfileVersion: null,
      validation: normalizeValidation(),
    });
  }
  return normalizePredictionSnapshot({
    horizon: normalizedHorizon,
    market_scope: normalizedMarketScope,
    system_status: status,
    reason_codes: [reasonCode],
    predictions: [],
    watchlist: [],
  }, normalizedHorizon, normalizedMarketScope);
}
