import { parseAllowedOrigins } from "./cors.ts";
import { createHandler } from "./handler.ts";
import { PostgrestRateLimiter } from "./rate-limit.ts";
import { SnapshotRepository } from "./repository.ts";

function positiveIntegerEnvironment(
  name: string,
  fallback: number,
  maximum: number,
): number {
  const value = Number(Deno.env.get(name) ?? "");
  return Number.isInteger(value) && value > 0
    ? Math.min(value, maximum)
    : fallback;
}

const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const databaseTimeoutMs = positiveIntegerEnvironment(
  "PREDICTION_DATABASE_TIMEOUT_MS",
  4_000,
  30_000,
);
const requestTimeoutMs = positiveIntegerEnvironment(
  "PREDICTION_REQUEST_TIMEOUT_MS",
  10_000,
  30_000,
);
const repository = new SnapshotRepository({
  supabaseUrl,
  serviceRoleKey,
  queryTimeoutMs: databaseTimeoutMs,
  readMode: Deno.env.get("PREDICTION_SNAPSHOT_READ_MODE") ?? "rpc",
});

const staleHoursValue = Number(
  Deno.env.get("PREDICTION_STALE_AFTER_HOURS") ?? "72",
);
const staleHours = Number.isFinite(staleHoursValue) && staleHoursValue > 0
  ? staleHoursValue
  : 72;
const rateLimitEnabled =
  Deno.env.get("PREDICTION_RATE_LIMIT_ENABLED")?.trim().toLowerCase() ===
    "true";
const rateLimitKeySecret = Deno.env.get("PREDICTION_RATE_LIMIT_KEY_SECRET") ??
  "";
const rateLimitClientAddressHeader =
  Deno.env.get("PREDICTION_RATE_LIMIT_CLIENT_IP_HEADER")?.trim() ||
  "CF-Connecting-IP";
const rateLimiter = rateLimitEnabled
  ? new PostgrestRateLimiter({
    supabaseUrl,
    serviceRoleKey,
    keySecret: rateLimitKeySecret,
    clientAddressHeader: rateLimitClientAddressHeader,
    maxRequests: positiveIntegerEnvironment(
      "PREDICTION_RATE_LIMIT_REQUESTS",
      30,
      10_000,
    ),
    windowSeconds: positiveIntegerEnvironment(
      "PREDICTION_RATE_LIMIT_WINDOW_SECONDS",
      60,
      3_600,
    ),
    queryTimeoutMs: databaseTimeoutMs,
  })
  : undefined;

Deno.serve(createHandler({
  repository,
  corsPolicy: parseAllowedOrigins(Deno.env.get("PREDICTION_ALLOWED_ORIGINS")),
  staleHours,
  requestTimeoutMs,
  rateLimiter,
}));
