import { corsHeaders, type CorsPolicy } from "./cors.ts";
import { ApiError } from "./errors.ts";
import {
  consoleRequestLogger,
  elapsedMilliseconds,
  type LogFields,
  requestId,
  type RequestLogger,
} from "./observability.ts";
import type { RateLimitDecision, RateLimiter } from "./rate-limit.ts";
import {
  normalizeTimeoutMs,
  runWithRequestDeadline,
} from "./request-deadline.ts";
import { API_CONTRACT_VERSION, buildSnapshot } from "./snapshot.ts";
import type { MarketScope, SnapshotRepositoryContract } from "./types.ts";

const RESEARCH_SETTINGS = new Set([
  "commission_discount",
  "minimum_fee",
  "estimated_order_notional_ntd",
  "max_adv_participation",
  "cost_profile",
  "max_single_position",
  "max_industry_position",
  "max_market_exposure",
]);
const DEFAULT_REQUEST_TIMEOUT_MS = 10_000;

interface HandlerOptions {
  repository: SnapshotRepositoryContract;
  corsPolicy: CorsPolicy;
  staleHours?: number;
  calendarReadyHourTaipei?: number;
  calendarLookbackDays?: number;
  requestTimeoutMs?: number;
  rateLimiter?: RateLimiter;
  logger?: RequestLogger;
  now?: () => Date;
}

function jsonResponse(
  payload: unknown,
  status: number,
  headers: Headers,
): Response {
  headers.set("Content-Type", "application/json; charset=utf-8");
  headers.set("X-Alpha-Lens-Contract", API_CONTRACT_VERSION);
  return new Response(JSON.stringify(payload), { status, headers });
}

interface SnapshotQuery {
  horizon: number;
  marketScope: MarketScope;
}

function validateQuery(url: URL): SnapshotQuery {
  const horizon = url.searchParams.get("horizon");
  if (horizon === null) {
    throw new ApiError(422, "HORIZON_REQUIRED", "horizon is required");
  }
  if (horizon !== "5") {
    throw new ApiError(
      422,
      "UNSUPPORTED_HORIZON",
      "Only horizon=5 is available",
    );
  }
  const marketValues = url.searchParams.getAll("market");
  const market = marketValues.length === 0 ? "TWSE" : marketValues[0];
  if (marketValues.length > 1 || (market !== "TWSE" && market !== "TPEX")) {
    throw new ApiError(
      422,
      "UNSUPPORTED_MARKET",
      "market must be TWSE or TPEX",
    );
  }
  const settings = [...url.searchParams.keys()].filter((name) =>
    RESEARCH_SETTINGS.has(name)
  );
  if (settings.length) {
    throw new ApiError(
      422,
      "RESEARCH_SETTINGS_NOT_AVAILABLE_FOR_STORED_SNAPSHOT",
      "Stored snapshots cannot be recalculated with request-time settings",
    );
  }
  const unknown = [...url.searchParams.keys()].filter((name) =>
    name !== "horizon" && name !== "market" && !RESEARCH_SETTINGS.has(name)
  );
  if (unknown.length) {
    throw new ApiError(
      422,
      "UNKNOWN_QUERY_PARAMETER",
      "Query contains unsupported parameters",
    );
  }
  return { horizon: 5, marketScope: market };
}

function applyRateLimitHeaders(
  headers: Headers,
  decision: RateLimitDecision,
): void {
  headers.set("X-RateLimit-Limit", String(decision.limit));
  headers.set("X-RateLimit-Remaining", String(decision.remaining));
  if (!decision.allowed) {
    headers.set("Retry-After", String(Math.max(1, decision.retryAfterSeconds)));
  }
}

function emitLog(
  logger: RequestLogger,
  level: "info" | "error",
  fields: LogFields,
): void {
  try {
    logger[level](fields);
  } catch {
    // Observability must never break the API response path.
  }
}

export function createHandler(
  options: HandlerOptions,
): (request: Request) => Promise<Response> {
  const requestTimeoutMs = normalizeTimeoutMs(
    options.requestTimeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS,
    DEFAULT_REQUEST_TIMEOUT_MS,
  );
  const logger = options.logger ?? consoleRequestLogger;

  return async (request: Request): Promise<Response> => {
    const startedAt = performance.now();
    const currentRequestId = requestId(request);
    let marketScope: MarketScope | null = null;
    let headers = new Headers({
      "Cache-Control": "no-store, max-age=0",
      "Pragma": "no-cache",
      "Vary": "Origin",
      "X-Content-Type-Options": "nosniff",
      "X-Request-Id": currentRequestId,
    });
    try {
      headers = corsHeaders(request, options.corsPolicy);
      headers.set("X-Request-Id", currentRequestId);
      if (request.method === "OPTIONS") {
        const response = new Response(null, { status: 204, headers });
        emitLog(logger, "info", {
          event: "prediction_snapshot_request_completed",
          request_id: currentRequestId,
          method: request.method,
          market_scope: null,
          status_code: 204,
          elapsed_ms: elapsedMilliseconds(startedAt),
        });
        return response;
      }
      if (request.method !== "GET") {
        throw new ApiError(405, "METHOD_NOT_ALLOWED", "Only GET is supported");
      }

      const requestedContract = request.headers.get("X-Alpha-Lens-Contract");
      if (requestedContract && requestedContract !== API_CONTRACT_VERSION) {
        throw new ApiError(
          409,
          "UNSUPPORTED_API_CONTRACT",
          "Requested API contract is not supported",
        );
      }
      const query = validateQuery(new URL(request.url));
      marketScope = query.marketScope;
      const snapshot = await runWithRequestDeadline(
        requestTimeoutMs,
        async (signal) => {
          if (options.rateLimiter) {
            const decision = await options.rateLimiter.consume(request, signal);
            applyRateLimitHeaders(headers, decision);
            if (!decision.allowed) {
              throw new ApiError(
                429,
                "PREDICTION_API_RATE_LIMITED",
                "Prediction snapshot request rate exceeded",
              );
            }
          }
          const observedAt = options.now?.() ?? new Date();
          const rows = await options.repository.loadLatest(
            query.horizon,
            query.marketScope,
            signal,
            observedAt,
          );
          return buildSnapshot(
            rows,
            query.marketScope,
            observedAt,
            {
              fallbackStaleHours: options.staleHours ?? 72,
              calendarReadyHourTaipei: options.calendarReadyHourTaipei,
              calendarLookbackDays: options.calendarLookbackDays,
            },
          );
        },
      );
      const response = jsonResponse(snapshot, 200, headers);
      emitLog(logger, "info", {
        event: "prediction_snapshot_request_completed",
        request_id: currentRequestId,
        method: request.method,
        market_scope: marketScope,
        status_code: 200,
        elapsed_ms: elapsedMilliseconds(startedAt),
      });
      return response;
    } catch (error) {
      const apiError = error instanceof ApiError ? error : new ApiError(
        500,
        "PREDICTION_SNAPSHOT_READ_FAILED",
        "Prediction snapshot could not be read",
      );
      emitLog(logger, apiError.status >= 500 ? "error" : "info", {
        event: "prediction_snapshot_request_failed",
        request_id: currentRequestId,
        method: request.method,
        market_scope: marketScope,
        status_code: apiError.status,
        error_code: apiError.code,
        elapsed_ms: elapsedMilliseconds(startedAt),
      });
      return jsonResponse(
        { code: apiError.code, request_id: currentRequestId },
        apiError.status,
        headers,
      );
    }
  };
}
