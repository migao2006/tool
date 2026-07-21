import { ApiError } from "./errors.ts";
import { normalizeTimeoutMs } from "./request-deadline.ts";
import { createTimedAbortSignal } from "./timed-abort.ts";

const CLIENT_ADDRESS_PATTERN = /^[0-9A-Fa-f:.]{2,64}$/u;

export interface RateLimitDecision {
  allowed: boolean;
  limit: number;
  remaining: number;
  retryAfterSeconds: number;
}

export interface RateLimiter {
  consume(request: Request, signal?: AbortSignal): Promise<RateLimitDecision>;
}

interface PostgrestRateLimiterConfig {
  supabaseUrl: string;
  serviceRoleKey: string;
  keySecret: string;
  clientAddressHeader: string;
  maxRequests: number;
  windowSeconds: number;
  queryTimeoutMs: number;
}

interface RateLimitRow {
  allowed: boolean;
  remaining: number;
  retry_after_seconds: number;
}

type FetchLike = typeof fetch;

function clientAddress(request: Request, headerName: string): string {
  const forwarded = request.headers.get(headerName)?.split(",", 1)[0];
  const normalized = forwarded?.trim() ?? "";
  return CLIENT_ADDRESS_PATTERN.test(normalized)
    ? normalized.toLowerCase()
    : "unattributed";
}

function importHmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
}

async function hmacSha256(key: CryptoKey, value: string): Promise<string> {
  const digest = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(value),
  );
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export class PostgrestRateLimiter implements RateLimiter {
  readonly #rpcUrl: string;
  readonly #keyPromise: Promise<CryptoKey>;
  readonly #queryTimeoutMs: number;

  constructor(
    readonly config: PostgrestRateLimiterConfig,
    readonly fetchImpl: FetchLike = fetch,
  ) {
    if (
      !config.supabaseUrl || !config.serviceRoleKey ||
      config.keySecret.trim().length < 32 ||
      !/^[A-Za-z0-9-]{1,64}$/u.test(config.clientAddressHeader) ||
      !Number.isInteger(config.maxRequests) || config.maxRequests < 1 ||
      config.maxRequests > 10_000 ||
      !Number.isInteger(config.windowSeconds) || config.windowSeconds < 1 ||
      config.windowSeconds > 3_600
    ) {
      throw new ApiError(
        500,
        "PREDICTION_RATE_LIMIT_NOT_CONFIGURED",
        "Rate limiting configuration is missing",
      );
    }
    this.#rpcUrl = `${
      config.supabaseUrl.replace(/\/$/u, "")
    }/rest/v1/rpc/consume_prediction_snapshot_rate_limit`;
    this.#keyPromise = importHmacKey(config.keySecret);
    this.#queryTimeoutMs = normalizeTimeoutMs(config.queryTimeoutMs, 4_000);
  }

  async consume(
    request: Request,
    parentSignal?: AbortSignal,
  ): Promise<RateLimitDecision> {
    const hmacKey = await this.#keyPromise;
    const key = await hmacSha256(
      hmacKey,
      `prediction-snapshot:${
        clientAddress(request, this.config.clientAddressHeader)
      }`,
    );
    const fetchSignal = createTimedAbortSignal(
      parentSignal,
      this.#queryTimeoutMs,
    );
    try {
      const response = await this.fetchImpl(this.#rpcUrl, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "Accept-Profile": "market_data",
          "Content-Profile": "market_data",
          apikey: this.config.serviceRoleKey,
          Authorization: `Bearer ${this.config.serviceRoleKey}`,
        },
        body: JSON.stringify({
          p_key_sha256: key,
          p_window_seconds: this.config.windowSeconds,
          p_max_requests: this.config.maxRequests,
        }),
        cache: "no-store",
        signal: fetchSignal.signal,
      });
      if (!response.ok) {
        throw new ApiError(
          503,
          "PREDICTION_RATE_LIMIT_UNAVAILABLE",
          "Rate limiting backend is unavailable",
        );
      }
      const payload: unknown = await response.json();
      const row = Array.isArray(payload) ? payload[0] as RateLimitRow : null;
      if (
        !row || typeof row.allowed !== "boolean" ||
        !Number.isInteger(row.remaining) || row.remaining < 0 ||
        row.remaining > this.config.maxRequests ||
        !Number.isInteger(row.retry_after_seconds) ||
        row.retry_after_seconds < 0 ||
        row.retry_after_seconds > this.config.windowSeconds ||
        (row.allowed && row.retry_after_seconds !== 0) ||
        (!row.allowed && (row.remaining !== 0 || row.retry_after_seconds < 1))
      ) {
        throw new ApiError(
          503,
          "PREDICTION_RATE_LIMIT_RESPONSE_INVALID",
          "Rate limiting backend returned an invalid response",
        );
      }
      return {
        allowed: row.allowed,
        limit: this.config.maxRequests,
        remaining: Math.max(0, row.remaining),
        retryAfterSeconds: Math.max(0, row.retry_after_seconds),
      };
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (parentSignal?.aborted) {
        throw parentSignal.reason instanceof ApiError
          ? parentSignal.reason
          : new ApiError(
            504,
            "PREDICTION_REQUEST_TIMEOUT",
            "Prediction snapshot request exceeded its deadline",
          );
      }
      if (fetchSignal.timedOut()) {
        throw new ApiError(
          503,
          "PREDICTION_RATE_LIMIT_TIMEOUT",
          "Rate limiting backend timed out",
        );
      }
      throw new ApiError(
        503,
        "PREDICTION_RATE_LIMIT_UNAVAILABLE",
        "Rate limiting backend is unavailable",
      );
    } finally {
      fetchSignal.cleanup();
    }
  }
}
