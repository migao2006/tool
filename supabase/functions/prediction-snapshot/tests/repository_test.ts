import { SnapshotRepository } from "../repository.ts";
import { assert, assertEquals } from "./assertions.ts";

Deno.test("repository keeps the service role key server-side", async () => {
  const requests: Request[] = [];
  const fakeFetch: typeof fetch = (input, init) => {
    const request = new Request(input, init);
    requests.push(request);
    return Promise.resolve(
      new Response("[]", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  };
  const secret = "server-only-service-role-key";
  const repository = new SnapshotRepository({
    supabaseUrl: "https://project.supabase.co",
    serviceRoleKey: secret,
  }, fakeFetch);

  assertEquals(await repository.loadLatest(5, "TPEX"), null);
  assertEquals(requests.length, 1);
  assertEquals(requests[0].headers.get("apikey"), secret);
  assertEquals(requests[0].headers.get("Accept-Profile"), "market_data");
  assertEquals(
    new URL(requests[0].url).searchParams.get("market_scope"),
    "eq.TPEX",
  );
  assert(
    !requests[0].url.includes(secret),
    "service role key must not enter the URL",
  );
});

Deno.test("repository only links one validation completed before the prediction run", async () => {
  const requests: Request[] = [];
  const fakeFetch: typeof fetch = (input, init) => {
    const request = new Request(input, init);
    requests.push(request);
    const table = new URL(request.url).pathname.split("/").at(-1);
    const payload = table === "prediction_runs"
      ? [{
        prediction_run_id: 7,
        as_of_date: "2026-07-17",
        decision_at: "2026-07-17T06:00:00+00:00",
        horizon: 5,
        model_bundle_version: "rank-research-v1",
        feature_schema_hash: "feature-hash",
        cost_profile_version: "tw-stock-base-v1",
        training_end_date: "2026-06-30",
        system_validation_status: "RESEARCH_ONLY",
        source_dates: {},
        latest_available_at: "2026-07-17T05:30:00+00:00",
        candidate_count: 0,
        watch_count: 0,
        no_trade_count: 0,
        hard_fail_count: 0,
        created_at: "2026-07-18T02:00:00+00:00",
      }]
      : table === "validation_runs"
      ? [
        validationRow(5, "2026-07-18T01:00:00+00:00"),
        validationRow(4, "2026-07-18T00:30:00+00:00"),
      ]
      : [];
    return Promise.resolve(Response.json(payload));
  };
  const repository = new SnapshotRepository({
    supabaseUrl: "https://project.supabase.co",
    serviceRoleKey: "server-only-service-role-key",
  }, fakeFetch);

  const rows = await repository.loadLatest(5, "TWSE");
  assert(rows !== null, "prediction run must be loaded");
  assertEquals(rows.validationLinkStatus, "AMBIGUOUS");
  assertEquals(rows.validationRun, null);
  const validationRequest = requests.find((request) =>
    new URL(request.url).pathname.endsWith("/validation_runs")
  );
  assert(validationRequest, "validation query must be issued");
  const query = new URL(validationRequest.url).searchParams;
  assertEquals(query.get("completed_at"), "lte.2026-07-18T02:00:00+00:00");
  assertEquals(query.get("limit"), "2");
  const runRequest = requests.find((request) =>
    new URL(request.url).pathname.endsWith("/prediction_runs")
  );
  assert(runRequest, "prediction run query must be issued");
  assertEquals(
    new URL(runRequest.url).searchParams.get("market_scope"),
    "eq.TWSE",
  );
});

function validationRow(validationRunId: number, completedAt: string) {
  return {
    validation_run_id: validationRunId,
    validation_status: "RESEARCH_ONLY",
    locked_holdout: false,
    frozen_config_hash: "config-hash",
    started_at: "2026-07-18T00:00:00+00:00",
    completed_at: completedAt,
    limitations: [],
  };
}
