import { parseAllowedOrigins } from "../cors.ts";
import { createHandler } from "../handler.ts";
import type { LogFields, RequestLogger } from "../observability.ts";
import type { RateLimiter } from "../rate-limit.ts";
import type {
  MarketScope,
  SnapshotRepositoryContract,
  SnapshotRows,
} from "../types.ts";
import { assert, assertEquals } from "./assertions.ts";

class EmptyRepository implements SnapshotRepositoryContract {
  calls = 0;

  loadLatest(
    horizon: number,
    marketScope: MarketScope,
    _signal?: AbortSignal,
  ): Promise<SnapshotRows | null> {
    this.calls += 1;
    assertEquals(horizon, 5);
    assertEquals(marketScope, "TWSE");
    return Promise.resolve(null);
  }
}

class HangingRepository implements SnapshotRepositoryContract {
  loadLatest(
    _horizon: number,
    _marketScope: MarketScope,
    signal?: AbortSignal,
  ): Promise<SnapshotRows | null> {
    return new Promise((_resolve, reject) => {
      if (signal?.aborted) {
        reject(signal.reason);
        return;
      }
      signal?.addEventListener("abort", () => reject(signal.reason), {
        once: true,
      });
    });
  }
}

function policy() {
  return parseAllowedOrigins("https://alpha.example");
}

Deno.test("request IDs are returned and structured completion logs are emitted", async () => {
  const entries: Array<{ level: string; fields: LogFields }> = [];
  const logger: RequestLogger = {
    info(fields) {
      entries.push({ level: "info", fields });
    },
    error(fields) {
      entries.push({ level: "error", fields });
    },
  };
  const repository = new EmptyRepository();
  const response = await createHandler({
    repository,
    corsPolicy: policy(),
    logger,
  })(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
      { headers: { "X-Request-Id": "request-valid-1234" } },
    ),
  );

  assertEquals(response.status, 200);
  assertEquals(response.headers.get("X-Request-Id"), "request-valid-1234");
  assertEquals(entries.length, 1);
  assertEquals(entries[0].level, "info");
  assertEquals(
    entries[0].fields.event,
    "prediction_snapshot_request_completed",
  );
  assertEquals(entries[0].fields.request_id, "request-valid-1234");
  assertEquals(entries[0].fields.status_code, 200);
  assert(typeof entries[0].fields.elapsed_ms === "number");
});

Deno.test("the overall request deadline aborts a hanging repository", async () => {
  const response = await createHandler({
    repository: new HangingRepository(),
    corsPolicy: policy(),
    requestTimeoutMs: 5,
  })(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
    ),
  );
  const payload = await response.json();

  assertEquals(response.status, 504);
  assertEquals(payload.code, "PREDICTION_REQUEST_TIMEOUT");
  assertEquals(payload.request_id, response.headers.get("X-Request-Id"));
});

Deno.test("rate limiting fails closed before database reads", async () => {
  const repository = new EmptyRepository();
  const rateLimiter: RateLimiter = {
    consume() {
      return Promise.resolve({
        allowed: false,
        limit: 30,
        remaining: 0,
        retryAfterSeconds: 17,
      });
    },
  };
  const response = await createHandler({
    repository,
    corsPolicy: policy(),
    rateLimiter,
  })(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
    ),
  );
  const payload = await response.json();

  assertEquals(response.status, 429);
  assertEquals(payload.code, "PREDICTION_API_RATE_LIMITED");
  assertEquals(response.headers.get("X-RateLimit-Limit"), "30");
  assertEquals(response.headers.get("X-RateLimit-Remaining"), "0");
  assertEquals(response.headers.get("Retry-After"), "17");
  assertEquals(repository.calls, 0);
});

Deno.test("CORS exposes request tracing and rate-limit response headers", async () => {
  const response = await createHandler({
    repository: new EmptyRepository(),
    corsPolicy: policy(),
  })(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
      {
        method: "OPTIONS",
        headers: { Origin: "https://alpha.example" },
      },
    ),
  );

  assertEquals(response.status, 204);
  assert(
    response.headers.get("Access-Control-Allow-Headers")?.includes(
      "X-Request-Id",
    ) === true,
  );
  const exposed = response.headers.get("Access-Control-Expose-Headers") ?? "";
  assert(exposed.includes("X-Request-Id"));
  assert(exposed.includes("X-RateLimit-Remaining"));
});
