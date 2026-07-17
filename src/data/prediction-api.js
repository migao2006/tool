import {
  CURRENT_HORIZON,
  isReleasedHorizon,
  normalizeHorizon,
} from "../core/five-day-contract.js";
import { createUnavailableSnapshot, normalizePredictionSnapshot } from "./prediction-contract.js";

/**
 * @typedef {Object} PredictionRecord
 * @property {string|null} as_of_date
 * @property {string|null} decision_at
 * @property {string} symbol
 * @property {string|null} name
 * @property {string} market
 * @property {string} industry
 * @property {number} horizon
 * @property {number|null} rank_score
 * @property {number|null} global_rank
 * @property {number|null} industry_rank
 * @property {number|null} calibrated_p_up
 * @property {number|null} calibrated_p_neutral
 * @property {number|null} calibrated_p_down
 * @property {number|null} net_q10
 * @property {number|null} net_q50
 * @property {number|null} net_q90
 * @property {number|null} estimated_round_trip_cost
 * @property {string} data_quality_status
 * @property {string} decision
 * @property {string[]} reason_codes
 * @property {string|null} model_version
 * @property {string|null} feature_schema_hash
 * @property {string|null} cost_profile_version
 * @property {string|null} training_end_date
 */

function getApiBaseUrl() {
  return document.documentElement.dataset.predictionApiBaseUrl?.trim() ?? "";
}

function addResearchSettings(url, settings) {
  if (!settings || typeof settings !== "object") return;
  const allowed = [
    "commission_discount",
    "minimum_fee",
    "estimated_order_notional_ntd",
    "max_adv_participation",
    "cost_profile",
    "max_single_position",
    "max_industry_position",
    "max_market_exposure",
  ];
  allowed.forEach((key) => {
    const value = settings[key];
    if (value !== null && value !== undefined && value !== "") url.searchParams.set(key, String(value));
  });
}

export async function loadPredictionSnapshot({
  horizon = CURRENT_HORIZON,
  settings,
  signal,
} = {}) {
  const normalizedHorizon = normalizeHorizon(horizon);
  if (!isReleasedHorizon(normalizedHorizon)) {
    return createUnavailableSnapshot({ horizon: normalizedHorizon, reasonCode: "MODEL_NOT_RELEASED" });
  }

  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl) {
    return createUnavailableSnapshot({ horizon: normalizedHorizon, reasonCode: "PREDICTION_API_NOT_CONFIGURED" });
  }

  const url = new URL("prediction-snapshot", `${apiBaseUrl.replace(/\/$/u, "")}/`);
  url.searchParams.set("horizon", String(normalizedHorizon));
  addResearchSettings(url, settings);
  const response = await fetch(url, { headers: { Accept: "application/json" }, signal });
  if (!response.ok) throw new Error(`預測 API 回應失敗：${response.status}`);
  return normalizePredictionSnapshot(await response.json(), normalizedHorizon);
}
