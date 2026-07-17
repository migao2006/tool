import { publicConfig } from "../core/public-config.js?v=api-3";

export class PredictionApiError extends Error {
  constructor(code, message, { status = null, cause = null } = {}) {
    super(message);
    this.name = "PredictionApiError";
    this.code = code;
    this.status = status;
    if (cause) this.cause = cause;
  }
}

export function resolvePredictionApiBaseUrl(config = publicConfig) {
  return globalThis.document?.documentElement?.dataset?.predictionApiBaseUrl?.trim()
    || config.predictionApiBaseUrl?.trim()
    || "";
}

function createRequestSignal(externalSignal, timeoutMs) {
  const controller = new AbortController();
  let timedOut = false;
  const forwardAbort = () => controller.abort(externalSignal?.reason);
  if (externalSignal?.aborted) forwardAbort();
  else externalSignal?.addEventListener("abort", forwardAbort, { once: true });
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  return Object.freeze({
    signal: controller.signal,
    timedOut: () => timedOut,
    cleanup: () => {
      clearTimeout(timer);
      externalSignal?.removeEventListener("abort", forwardAbort);
    },
  });
}

function buildUrl(path, query, config) {
  const apiBaseUrl = resolvePredictionApiBaseUrl(config);
  if (!apiBaseUrl) {
    throw new PredictionApiError("PREDICTION_API_NOT_CONFIGURED", "預測 API 尚未設定。");
  }
  let url;
  try {
    const resolvedBaseUrl = new URL(apiBaseUrl, globalThis.location?.href);
    url = new URL(path.replace(/^\//u, ""), `${resolvedBaseUrl.toString().replace(/\/$/u, "")}/`);
  } catch (error) {
    throw new PredictionApiError("PREDICTION_API_CONFIG_INVALID", "預測 API 網址格式不正確。", { cause: error });
  }
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") {
      url.searchParams.set(key, String(value));
    }
  });
  return url;
}

export async function requestPredictionApi(path, {
  method = "GET",
  query,
  body,
  accessToken,
  signal,
  config = publicConfig,
} = {}) {
  const url = buildUrl(path, query, config);
  const timeoutMs = Number.isFinite(config.predictionApiTimeoutMs) && config.predictionApiTimeoutMs > 0
    ? config.predictionApiTimeoutMs
    : 12_000;
  const request = createRequestSignal(signal, timeoutMs);
  const headers = {
    Accept: "application/json",
    "X-Alpha-Lens-Contract": config.predictionApiContractVersion || "prediction-snapshot.v1",
  };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;

  try {
    const response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      signal: request.signal,
    });
    if (!response.ok) {
      const code = response.status === 401
        ? "PREDICTION_API_UNAUTHORIZED"
        : response.status === 403
          ? "PREDICTION_API_FORBIDDEN"
          : "PREDICTION_API_HTTP_ERROR";
      throw new PredictionApiError(code, `預測 API 回應失敗：${response.status}`, { status: response.status });
    }
    if (response.status === 204) return null;
    try {
      return await response.json();
    } catch (error) {
      throw new PredictionApiError("PREDICTION_API_INVALID_JSON", "預測 API 未回傳有效 JSON。", { cause: error });
    }
  } catch (error) {
    if (request.timedOut()) {
      throw new PredictionApiError("PREDICTION_API_TIMEOUT", "預測 API 回應逾時。", { cause: error });
    }
    if (signal?.aborted || error instanceof PredictionApiError) throw error;
    throw new PredictionApiError(
      "PREDICTION_API_NETWORK_ERROR",
      "目前無法連線至預測 API。",
      { cause: error },
    );
  } finally {
    request.cleanup();
  }
}
