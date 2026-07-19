import { publicConfig } from "../core/public-config.js?v=api-3";
import { createRequestSignal } from "./request-signal.js?v=request-signal-1";

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

const HTTP_ERRORS = Object.freeze({
  401: ["PREDICTION_API_UNAUTHORIZED", "登入狀態已失效，請重新登入。"],
  403: ["PREDICTION_API_FORBIDDEN", "沒有權限使用此資料。"],
  404: ["PREDICTION_API_NOT_FOUND", "預測 API 端點不存在。"],
  409: ["PREDICTION_API_VERSION_CONFLICT", "資料與模型版本不一致。"],
  422: ["PREDICTION_API_INVALID_REQUEST", "研究設定或查詢參數不合法。"],
  429: ["PREDICTION_API_RATE_LIMITED", "請求過於頻繁，請稍後再試。"],
});

async function createHttpError(response) {
  const [fallbackCode, message] = HTTP_ERRORS[response.status]
    ?? ["PREDICTION_API_HTTP_ERROR", "預測服務暫時無法使用。"];
  let serverCode = null;
  try {
    const payload = await response.json();
    if (typeof payload?.code === "string" && /^[A-Z][A-Z0-9_]{0,79}$/u.test(payload.code)) {
      serverCode = payload.code;
    }
  } catch {
    // Error bodies are optional and never replace the stable user-facing copy.
  }
  return new PredictionApiError(serverCode ?? fallbackCode, message, { status: response.status });
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
      throw await createHttpError(response);
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
