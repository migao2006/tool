import { corsHeaders, type CorsPolicy } from "./cors.ts";
import { ApiError } from "./errors.ts";
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

interface HandlerOptions {
  repository: SnapshotRepositoryContract;
  corsPolicy: CorsPolicy;
  staleHours?: number;
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

export function createHandler(
  options: HandlerOptions,
): (request: Request) => Promise<Response> {
  return async (request: Request): Promise<Response> => {
    let headers = new Headers({
      "Cache-Control": "no-store, max-age=0",
      "Pragma": "no-cache",
      "Vary": "Origin",
      "X-Content-Type-Options": "nosniff",
    });
    try {
      headers = corsHeaders(request, options.corsPolicy);
      if (request.method === "OPTIONS") {
        return new Response(null, { status: 204, headers });
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
      const { horizon, marketScope } = validateQuery(new URL(request.url));
      const rows = await options.repository.loadLatest(horizon, marketScope);
      const snapshot = buildSnapshot(
        rows,
        marketScope,
        options.now?.() ?? new Date(),
        options.staleHours ?? 72,
      );
      return jsonResponse(snapshot, 200, headers);
    } catch (error) {
      const apiError = error instanceof ApiError ? error : new ApiError(
        500,
        "PREDICTION_SNAPSHOT_READ_FAILED",
        "Prediction snapshot could not be read",
      );
      return jsonResponse({ code: apiError.code }, apiError.status, headers);
    }
  };
}
