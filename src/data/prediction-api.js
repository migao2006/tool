import {
  CURRENT_HORIZON,
  isReleasedHorizon,
  normalizeHorizon,
} from "../core/five-day-contract.js";
import { publicConfig } from "../core/public-config.js?v=api-3";
import {
  PredictionApiError,
  requestPredictionApi,
  resolvePredictionApiBaseUrl,
} from "./api-client.js?v=api-4";
import { createUnavailableSnapshot, normalizePredictionSnapshot } from "./prediction-contract.js?v=api-4";
import { readSupabaseAccessToken } from "./session-token.js?v=api-4";
import { isSupabaseSdkLoadError } from "./supabase-sdk-loader.js?v=auth-1";

export { PredictionApiError };

const RESEARCH_SETTING_KEYS = Object.freeze([
  "commission_discount",
  "minimum_fee",
  "estimated_order_notional_ntd",
  "max_adv_participation",
  "cost_profile",
  "max_single_position",
  "max_industry_position",
  "max_market_exposure",
]);

function predictionQuery(horizon, settings) {
  const query = { horizon };
  if (!settings || typeof settings !== "object") return query;
  RESEARCH_SETTING_KEYS.forEach((key) => {
    const value = settings[key];
    if (value !== null && value !== undefined && value !== "") query[key] = value;
  });
  return query;
}

export async function loadPredictionSnapshot({
  horizon = CURRENT_HORIZON,
  settings,
  signal,
  config = publicConfig,
} = {}) {
  const normalizedHorizon = normalizeHorizon(horizon);
  if (!isReleasedHorizon(normalizedHorizon)) {
    return createUnavailableSnapshot({ horizon: normalizedHorizon, reasonCode: "MODEL_NOT_RELEASED" });
  }
  if (!resolvePredictionApiBaseUrl(config)) {
    return createUnavailableSnapshot({ horizon: normalizedHorizon, reasonCode: "PREDICTION_API_NOT_CONFIGURED" });
  }
  let accessToken = null;
  try {
    accessToken = await readSupabaseAccessToken(config);
  } catch (error) {
    if (!isSupabaseSdkLoadError(error)) {
      globalThis.Sentry?.captureException?.(error);
    }
  }
  const payload = await requestPredictionApi("prediction-snapshot", {
    query: predictionQuery(normalizedHorizon, settings),
    accessToken,
    signal,
    config,
  });
  try {
    return normalizePredictionSnapshot(payload, normalizedHorizon);
  } catch (error) {
    throw new PredictionApiError(
      "PREDICTION_API_CONTRACT_ERROR",
      "預測 API 回傳內容不符合目前契約。",
      { cause: error },
    );
  }
}
