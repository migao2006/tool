import { ApiError } from "../errors.ts";
import { PostgrestRateLimiter } from "../rate-limit.ts";
import { assert, assertEquals } from "./assertions.ts";

const CONFIG = {
  supabaseUrl: "https://project.supabase.co",
  serviceRoleKey: "server-only-service-role-key",
  keySecret: "rate-limit-hmac-secret-that-is-at-least-32-bytes",
  clientAddressHeader: "CF-Connecting-IP",
  maxRequests: 30,
  windowSeconds: 60,
  queryTimeoutMs: 100,
};

Deno.test("rate limiter stores only a deterministic HMAC client key", async () => {
  const bodies: Array<Record<string, unknown>> = [];
  const fakeFetch: typeof fetch = (_input, init) => {
    const requestInit = init as { body?: BodyInit | null } | undefined;
    bodies.push(JSON.parse(String(requestInit?.body)));
    return Promise.resolve(Response.json([{
      allowed: true,
      remaining: 29,
      retry_after_seconds: 0,
    }]));
  };
  const limiter = new PostgrestRateLimiter(CONFIG, fakeFetch);
  const firstRequest = new Request("https://api.example", {
    headers: { "CF-Connecting-IP": "203.0.113.7" },
  });
  const secondRequest = new Request("https://api.example", {
    headers: { "CF-Connecting-IP": "203.0.113.7" },
  });

  const decision = await limiter.consume(firstRequest);
  await limiter.consume(secondRequest);

  assertEquals(decision.allowed, true);
  assertEquals(decision.limit, 30);
  assertEquals(bodies.length, 2);
  const firstKey = String(bodies[0].p_key_sha256);
  assert(/^[0-9a-f]{64}$/u.test(firstKey));
  assertEquals(firstKey, bodies[1].p_key_sha256);
  assert(!JSON.stringify(bodies).includes("203.0.113.7"));
  assertEquals(bodies[0].p_window_seconds, 60);
  assertEquals(bodies[0].p_max_requests, 30);
});

Deno.test("rate limiter ignores unconfigured spoofable address headers", async () => {
  const bodies: Array<Record<string, unknown>> = [];
  const fakeFetch: typeof fetch = (_input, init) => {
    const requestInit = init as { body?: BodyInit | null } | undefined;
    bodies.push(JSON.parse(String(requestInit?.body)));
    return Promise.resolve(Response.json([{
      allowed: true,
      remaining: 29,
      retry_after_seconds: 0,
    }]));
  };
  const limiter = new PostgrestRateLimiter(CONFIG, fakeFetch);

  await limiter.consume(
    new Request("https://api.example", {
      headers: { "X-Forwarded-For": "203.0.113.88" },
    }),
  );
  await limiter.consume(new Request("https://api.example"));

  assertEquals(bodies.length, 2);
  assertEquals(bodies[0].p_key_sha256, bodies[1].p_key_sha256);
  assert(!JSON.stringify(bodies).includes("203.0.113.88"));
});

Deno.test("rate limiter rejects an invalid client address header name", () => {
  let error: unknown = null;
  try {
    new PostgrestRateLimiter({
      ...CONFIG,
      clientAddressHeader: "CF-Connecting-IP\r\nX-Injected",
    });
  } catch (caught) {
    error = caught;
  }
  assert(error instanceof ApiError);
  assertEquals(error.code, "PREDICTION_RATE_LIMIT_NOT_CONFIGURED");
});

Deno.test("rate limiter requires a dedicated HMAC secret", () => {
  let error: unknown = null;
  try {
    new PostgrestRateLimiter({ ...CONFIG, keySecret: "too-short" });
  } catch (caught) {
    error = caught;
  }
  assert(error instanceof ApiError);
  assertEquals(error.code, "PREDICTION_RATE_LIMIT_NOT_CONFIGURED");
});

Deno.test("rate limiter query timeout fails closed", async () => {
  const fakeFetch: typeof fetch = (_input, init) =>
    new Promise((_resolve, reject) => {
      const requestInit = init as { signal?: AbortSignal | null } | undefined;
      const signal = requestInit?.signal;
      if (signal?.aborted) {
        reject(signal.reason);
        return;
      }
      signal?.addEventListener("abort", () => reject(signal.reason), {
        once: true,
      });
    });
  const limiter = new PostgrestRateLimiter(
    { ...CONFIG, queryTimeoutMs: 5 },
    fakeFetch,
  );

  let error: unknown = null;
  try {
    await limiter.consume(new Request("https://api.example"));
  } catch (caught) {
    error = caught;
  }
  assert(error instanceof ApiError);
  assertEquals(error.code, "PREDICTION_RATE_LIMIT_TIMEOUT");
  assertEquals(error.status, 503);
});

Deno.test("rate limiter rejects an inconsistent backend decision", async () => {
  const fakeFetch: typeof fetch = () =>
    Promise.resolve(Response.json([{
      allowed: false,
      remaining: 1,
      retry_after_seconds: 0,
    }]));
  const limiter = new PostgrestRateLimiter(CONFIG, fakeFetch);

  let error: unknown = null;
  try {
    await limiter.consume(new Request("https://api.example"));
  } catch (caught) {
    error = caught;
  }
  assert(error instanceof ApiError);
  assertEquals(error.code, "PREDICTION_RATE_LIMIT_RESPONSE_INVALID");
  assertEquals(error.status, 503);
});
