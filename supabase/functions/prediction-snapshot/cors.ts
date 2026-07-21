import { ApiError } from "./errors.ts";

export interface CorsPolicy {
  allowedOrigins: ReadonlySet<string>;
}

export function parseAllowedOrigins(value: string | undefined): CorsPolicy {
  const configured = (value ?? "")
    .split(",")
    .map((origin) => origin.trim().replace(/\/$/u, ""))
    .filter(Boolean);
  const origins = configured.map((origin) => {
    try {
      const parsed = new URL(origin);
      if (parsed.origin !== origin) throw new Error("origin contains a path");
      return parsed.origin;
    } catch {
      throw new ApiError(
        500,
        "CORS_ALLOWLIST_INVALID",
        "PREDICTION_ALLOWED_ORIGINS contains an invalid origin",
      );
    }
  });
  return { allowedOrigins: new Set(origins) };
}

export function corsHeaders(request: Request, policy: CorsPolicy): Headers {
  const headers = new Headers({
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Vary": "Origin",
    "X-Content-Type-Options": "nosniff",
  });
  const rawOrigin = request.headers.get("Origin");
  if (!rawOrigin) return headers;

  const origin = rawOrigin.replace(/\/$/u, "");
  if (!policy.allowedOrigins.has(origin)) {
    throw new ApiError(
      403,
      "ORIGIN_NOT_ALLOWED",
      "Request origin is not allowed",
    );
  }
  headers.set("Access-Control-Allow-Origin", rawOrigin);
  headers.set("Access-Control-Allow-Methods", "GET, OPTIONS");
  headers.set(
    "Access-Control-Allow-Headers",
    "Authorization, Content-Type, X-Alpha-Lens-Contract, X-Request-Id",
  );
  headers.set(
    "Access-Control-Expose-Headers",
    "X-Alpha-Lens-Contract, X-Request-Id, X-RateLimit-Limit, X-RateLimit-Remaining, Retry-After",
  );
  headers.set("Access-Control-Max-Age", "600");
  return headers;
}
