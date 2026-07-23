import {
  CURRENT_HORIZON,
  isReleasedHorizon,
  normalizeHorizon,
} from "../core/five-day-contract.js";
import {
  DEFAULT_MARKET_SCOPE,
  normalizeMarketScope,
} from "../core/market-scope.js";
import { publicConfig } from "../core/public-config.js?v=api-3";
import {
  PredictionApiError,
  requestPredictionApi,
  resolvePredictionApiBaseUrl,
} from "./api-client.js?v=api-5";
import { createUnavailableSnapshot, normalizePredictionSnapshot } from "./prediction-contract.js?v=classification-2";
import { readSupabaseAccessToken } from "./session-token.js?v=api-4";
import { isSupabaseSdkLoadError } from "./supabase-sdk-loader.js?v=auth-1";

export { PredictionApiError };

function predictionQuery(horizon, marketScope) {
  return { horizon, market: marketScope };
}

export async function loadPredictionSnapshot({
  horizon = CURRENT_HORIZON,
  market = DEFAULT_MARKET_SCOPE,
  signal,
  config = publicConfig,
} = {}) {
  const normalizedHorizon = normalizeHorizon(horizon);
  const normalizedMarket = normalizeMarketScope(market);
  if (!isReleasedHorizon(normalizedHorizon)) {
    return createUnavailableSnapshot({
      horizon: normalizedHorizon,
      marketScope: normalizedMarket,
      reasonCode: "UNSUPPORTED_HORIZON",
    });
  }
  if (!resolvePredictionApiBaseUrl(config)) {
    return createUnavailableSnapshot({
      horizon: normalizedHorizon,
      marketScope: normalizedMarket,
      reasonCode: "PREDICTION_API_NOT_CONFIGURED",
    });
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
    // The current endpoint reads an immutable stored snapshot. Device research
    // preferences remain local until the API can produce a separately versioned
    // result for those settings; forwarding them would invalidate the request.
    query: predictionQuery(normalizedHorizon, normalizedMarket),
    accessToken,
    signal,
    config,
  });
  try {
    return normalizePredictionSnapshot(payload, normalizedHorizon, normalizedMarket);
  } catch (error) {
    throw new PredictionApiError(
      "PREDICTION_API_CONTRACT_ERROR",
      "預測 API 回傳內容不符合目前契約。",
      { cause: error },
    );
  }
}
