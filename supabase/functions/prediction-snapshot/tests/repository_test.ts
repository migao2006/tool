import { SnapshotRepository } from "../repository.ts";
import { assert, assertEquals } from "./assertions.ts";
import { snapshotRows } from "./fixtures.ts";

const OBSERVED_AT = new Date("2026-07-20T08:30:00.000Z");

Deno.test("repository reads a snapshot through exactly one service-role RPC", async () => {
  const requests: Request[] = [];
  const fakeFetch: typeof fetch = (input, init) => {
    const request = new Request(input, init);
    requests.push(request);
    return Promise.resolve(Response.json(null));
  };
  const secret = "server-only-service-role-key";
  const repository = new SnapshotRepository({
    supabaseUrl: "https://project.supabase.co",
    serviceRoleKey: secret,
    readMode: "rpc",
  }, fakeFetch);

  assertEquals(
    await repository.loadLatest(5, "TPEX", undefined, OBSERVED_AT),
    null,
  );
  assertEquals(requests.length, 1);
  const request = requests[0];
  assertEquals(request.method, "POST");
  assertEquals(
    new URL(request.url).pathname,
    "/rest/v1/rpc/get_prediction_snapshot_rows_v2",
  );
  assertEquals(request.headers.get("apikey"), secret);
  assertEquals(request.headers.get("Accept-Profile"), "market_data");
  assertEquals(request.headers.get("Content-Profile"), "market_data");
  assertEquals(await request.clone().json(), {
    p_horizon: 5,
    p_market_scope: "TPEX",
    p_observed_at: OBSERVED_AT.toISOString(),
  });
  assert(
    !request.url.includes(secret),
    "service role key must not enter the URL",
  );
  assert(
    !request.url.includes("prediction_runs"),
    "the primary path must not use request-time table fan-out",
  );
});

Deno.test("rpc mode does not fall back when the RPC is missing", async () => {
  const requests: Request[] = [];
  const fakeFetch: typeof fetch = (input, init) => {
    requests.push(new Request(input, init));
    return Promise.resolve(Response.json({
      code: "PGRST202",
      message:
        "Could not find the function market_data.get_prediction_snapshot_rows_v2",
    }, { status: 404 }));
  };
  const repository = new SnapshotRepository({
    supabaseUrl: "https://project.supabase.co",
    serviceRoleKey: "server-only-service-role-key",
    readMode: "rpc",
  }, fakeFetch);

  let error: unknown = null;
  try {
    await repository.loadLatest(5, "TWSE");
  } catch (caught) {
    error = caught;
  }
  assert(error instanceof Error);
  assertEquals(
    (error as { code?: string }).code,
    "PREDICTION_SNAPSHOT_RPC_NOT_DEPLOYED",
  );
  assertEquals(requests.length, 1);
});

Deno.test("the default mode fails closed when the RPC is not deployed", async () => {
  const requests: Request[] = [];
  const fakeFetch: typeof fetch = (input, init) => {
    requests.push(new Request(input, init));
    return Promise.resolve(Response.json({
      code: "PGRST202",
      message:
        "Could not find the function market_data.get_prediction_snapshot_rows_v2",
    }, { status: 404 }));
  };
  const repository = new SnapshotRepository({
    supabaseUrl: "https://project.supabase.co",
    serviceRoleKey: "server-only-service-role-key",
  }, fakeFetch);

  const error = await capturedError(() =>
    repository.loadLatest(5, "TWSE", undefined, OBSERVED_AT)
  );
  assertEquals(error.code, "PREDICTION_SNAPSHOT_RPC_NOT_DEPLOYED");
  assertEquals(requests.length, 1);
  assertEquals(
    new URL(requests[0].url).pathname,
    "/rest/v1/rpc/get_prediction_snapshot_rows_v2",
  );
});

Deno.test("RPC ambiguity is treated as a database failure, not as an undeployed RPC", async () => {
  const requests: Request[] = [];
  const fakeFetch: typeof fetch = (input, init) => {
    requests.push(new Request(input, init));
    return Promise.resolve(Response.json({
      code: "PGRST203",
      message: "Could not choose the best candidate function",
    }, { status: 300 }));
  };
  const repository = new SnapshotRepository({
    supabaseUrl: "https://project.supabase.co",
    serviceRoleKey: "server-only-service-role-key",
    readMode: "rpc",
  }, fakeFetch);

  const error = await capturedError(() =>
    repository.loadLatest(5, "TWSE", undefined, OBSERVED_AT)
  );
  assertEquals(error.code, "PREDICTION_DATABASE_READ_FAILED");
  assertEquals(requests.length, 1);
});

Deno.test("repository accepts the complete RPC payload without extra reads", async () => {
  const requests: Request[] = [];
  const expected = snapshotRows();
  expected.validationRun = null;
  expected.validationMetrics = [];
  expected.backtests = [];
  expected.validationLinkStatus = "AMBIGUOUS";
  const fakeFetch: typeof fetch = (input, init) => {
    requests.push(new Request(input, init));
    return Promise.resolve(Response.json(expected));
  };
  const repository = new SnapshotRepository({
    supabaseUrl: "https://project.supabase.co",
    serviceRoleKey: "server-only-service-role-key",
    readMode: "rpc",
  }, fakeFetch);

  const actual = await repository.loadLatest(5, "TWSE", undefined, OBSERVED_AT);
  assertEquals(actual, expected);
  assertEquals(requests.length, 1);
});

Deno.test("repository tolerates PostgREST scalar wrappers", async () => {
  const expected = snapshotRows();
  const wrappedPayloads = [
    { get_prediction_snapshot_rows_v2: expected },
    [{ get_prediction_snapshot_rows_v2: expected }],
  ];
  for (const payload of wrappedPayloads) {
    const fakeFetch: typeof fetch = () =>
      Promise.resolve(Response.json(payload));
    const repository = new SnapshotRepository({
      supabaseUrl: "https://project.supabase.co",
      serviceRoleKey: "server-only-service-role-key",
      readMode: "rpc",
    }, fakeFetch);
    assertEquals(
      await repository.loadLatest(5, "TWSE", undefined, OBSERVED_AT),
      expected,
    );
  }
});

Deno.test("legacy mode remains an explicit emergency rollback path", async () => {
  const requests: Request[] = [];
  const fakeFetch: typeof fetch = (input, init) => {
    const request = new Request(input, init);
    requests.push(request);
    return Promise.resolve(Response.json([]));
  };
  const repository = new SnapshotRepository({
    supabaseUrl: "https://project.supabase.co",
    serviceRoleKey: "server-only-service-role-key",
    readMode: "legacy",
  }, fakeFetch);

  assertEquals(
    await repository.loadLatest(5, "TWSE", undefined, OBSERVED_AT),
    null,
  );
  assertEquals(requests.length, 1);
  assertEquals(
    new URL(requests[0].url).pathname,
    "/rest/v1/prediction_runs",
  );
  const query = new URL(requests[0].url).searchParams;
  assertEquals(query.get("decision_at"), `lte.${OBSERVED_AT.toISOString()}`);
  assertEquals(
    query.get("latest_available_at"),
    `lte.${OBSERVED_AT.toISOString()}`,
  );
  assertEquals(query.get("created_at"), `lte.${OBSERVED_AT.toISOString()}`);
});

Deno.test("repository rejects an incomplete RPC response", async () => {
  const fakeFetch: typeof fetch = () =>
    Promise.resolve(Response.json({ run: {}, predictions: [] }));
  const repository = new SnapshotRepository({
    supabaseUrl: "https://project.supabase.co",
    serviceRoleKey: "server-only-service-role-key",
    readMode: "rpc",
  }, fakeFetch);

  const error = await capturedError(() =>
    repository.loadLatest(5, "TWSE", undefined, OBSERVED_AT)
  );
  assertEquals(error.code, "PREDICTION_DATABASE_RESPONSE_INVALID");
});

Deno.test("repository rejects an unknown read mode", () => {
  let error: unknown = null;
  try {
    new SnapshotRepository({
      supabaseUrl: "https://project.supabase.co",
      serviceRoleKey: "server-only-service-role-key",
      readMode: "silent-fallback",
    });
  } catch (caught) {
    error = caught;
  }
  assert(error instanceof Error);
  assertEquals(
    (error as { code?: string }).code,
    "PREDICTION_API_NOT_CONFIGURED",
  );
});

Deno.test("repository database reads have a bounded timeout", async () => {
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
  const repository = new SnapshotRepository({
    supabaseUrl: "https://project.supabase.co",
    serviceRoleKey: "server-only-service-role-key",
    queryTimeoutMs: 5,
    readMode: "rpc",
  }, fakeFetch);

  const error = await capturedError(() =>
    repository.loadLatest(5, "TWSE", undefined, OBSERVED_AT)
  );
  assertEquals(error.code, "PREDICTION_DATABASE_TIMEOUT");
});

async function capturedError(
  operation: () => Promise<unknown>,
): Promise<{ code?: string }> {
  let error: unknown = null;
  try {
    await operation();
  } catch (caught) {
    error = caught;
  }
  assert(error instanceof Error);
  return error as { code?: string };
}
