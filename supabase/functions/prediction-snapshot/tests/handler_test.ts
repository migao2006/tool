import { parseAllowedOrigins } from "../cors.ts";
import { createHandler } from "../handler.ts";
import type { SnapshotRepositoryContract, SnapshotRows } from "../types.ts";
import { assert, assertEquals } from "./assertions.ts";
import { snapshotRows } from "./fixtures.ts";

class FakeRepository implements SnapshotRepositoryContract {
  constructor(readonly rows: SnapshotRows | null) {}
  loadLatest(horizon: number): Promise<SnapshotRows | null> {
    assertEquals(horizon, 5);
    return Promise.resolve(this.rows);
  }
}

function handler(rows: SnapshotRows | null) {
  return createHandler({
    repository: new FakeRepository(rows),
    corsPolicy: parseAllowedOrigins(
      "https://alpha.example,http://127.0.0.1:3000",
    ),
    now: () => new Date("2026-07-17T07:00:00+00:00"),
  });
}

Deno.test("anonymous GET returns an honest empty research snapshot", async () => {
  const response = await handler(null)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
    ),
  );
  const payload = await response.json();
  assertEquals(response.status, 200);
  assertEquals(response.headers.get("Cache-Control"), "no-store, max-age=0");
  assertEquals(payload.system_status, "RESEARCH_ONLY");
  assertEquals(payload.as_of_date, null);
  assertEquals(payload.predictions, []);
});

Deno.test("stored research rows expose only eligible predictions and real exclusions", async () => {
  const response = await handler(snapshotRows())(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
      {
        headers: {
          Origin: "https://alpha.example",
          Authorization: "Bearer opaque-user-token",
        },
      },
    ),
  );
  const payload = await response.json();
  assertEquals(response.status, 200);
  assertEquals(
    response.headers.get("Access-Control-Allow-Origin"),
    "https://alpha.example",
  );
  assertEquals(payload.predictions.length, 1);
  assertEquals(payload.predictions[0].symbol, "2330");
  assertEquals(payload.predictions[0].decision, "CANDIDATE");
  assertEquals(payload.predictions[0].rank_score, 100);
  assertEquals(payload.predictions[0].liquidity_bucket, null);
  assertEquals(payload.data_quality_hard_fail, false);
  assertEquals(payload.excluded[0].symbol, "9999");
  assertEquals(payload.watchlist, []);
  assertEquals(payload.validation.fold_metrics[0].metric_value, 0.42);
  assert(
    !JSON.stringify(payload).includes("opaque-user-token"),
    "token must not be reflected",
  );
});

Deno.test("decision category counts must match the run manifest", async () => {
  const rows = snapshotRows();
  rows.run.candidate_count = 0;
  rows.run.watch_count = 1;

  const response = await handler(rows)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
    ),
  );
  assertEquals(response.status, 409);
  assertEquals(
    (await response.json()).code,
    "PREDICTION_DECISION_COUNT_MISMATCH",
  );
});

Deno.test("unsupported horizons and request-time recalculation fail closed", async () => {
  const unsupported = await handler(null)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=3",
    ),
  );
  assertEquals(unsupported.status, 422);
  assertEquals((await unsupported.json()).code, "UNSUPPORTED_HORIZON");

  const settings = await handler(null)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5&commission_discount=0.5",
    ),
  );
  assertEquals(settings.status, 422);
  assertEquals(
    (await settings.json()).code,
    "RESEARCH_SETTINGS_NOT_AVAILABLE_FOR_STORED_SNAPSHOT",
  );
});

Deno.test("CORS allowlist and row-count manifest are enforced", async () => {
  const blocked = await handler(null)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
      { headers: { Origin: "https://attacker.example" } },
    ),
  );
  assertEquals(blocked.status, 403);
  assertEquals(blocked.headers.get("Access-Control-Allow-Origin"), null);

  const rows = snapshotRows();
  rows.run.candidate_count = 99;
  const incomplete = await handler(rows)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
    ),
  );
  assertEquals(incomplete.status, 409);
  assertEquals(
    (await incomplete.json()).code,
    "PREDICTION_SNAPSHOT_INCOMPLETE",
  );
});

Deno.test("database PASS is downgraded until the public contract is complete", async () => {
  const rows = snapshotRows();
  rows.run.system_validation_status = "PASS";
  rows.run.hard_fail_count = 0;
  rows.run.no_trade_count = 0;
  rows.predictions = rows.predictions.slice(0, 1);
  rows.securities = rows.securities.slice(0, 1);
  rows.audits = [];
  if (rows.validationRun) {
    rows.validationRun.validation_status = "PASS";
    rows.validationRun.locked_holdout = true;
  }
  rows.markets.push({ ...rows.markets[0], market: "TPEX" });

  const response = await handler(rows)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
    ),
  );
  const payload = await response.json();
  assertEquals(response.status, 200);
  assertEquals(payload.system_status, "RESEARCH_ONLY");
  assert(
    payload.reason_codes.includes("FORMAL_SNAPSHOT_CONTRACT_INCOMPLETE"),
    "missing gate source dates must prevent a formal PASS",
  );
});

Deno.test("audit-only hard fails remain visible in excluded", async () => {
  const rows = snapshotRows();
  rows.run.no_trade_count = 0;
  rows.predictions = rows.predictions.slice(0, 1);

  const response = await handler(rows)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
    ),
  );
  const payload = await response.json();
  assertEquals(response.status, 200);
  assertEquals(payload.predictions.length, 1);
  assertEquals(payload.excluded.length, 1);
  assertEquals(payload.excluded[0].symbol, "9999");
  assertEquals(payload.excluded[0].decision, "NO_TRADE");
});

Deno.test("a non-hard quality failure does not exclude the whole stock", async () => {
  const rows = snapshotRows();
  rows.run.hard_fail_count = 0;
  rows.audits[0].hard_fail = false;
  rows.audits[0].reason_codes = ["DATA_QUALITY_WARNING"];

  const response = await handler(rows)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
    ),
  );
  const payload = await response.json();
  assertEquals(response.status, 200);
  assertEquals(payload.predictions.length, 2);
  assertEquals(payload.excluded, []);
  assertEquals(payload.predictions[1].data_quality_status, "WARN");
  assertEquals(payload.predictions[1].data_quality_hard_fail, false);
});

Deno.test("publisher compatibility markers restore a research warning", async () => {
  const rows = snapshotRows();
  rows.run.hard_fail_count = 0;
  rows.audits = [];
  rows.predictions[1].reason_codes = [
    "RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY",
    "RESEARCH_DATA_QUALITY_WARN",
  ];

  const response = await handler(rows)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
    ),
  );
  const payload = await response.json();
  assertEquals(response.status, 200);
  assertEquals(payload.predictions.length, 2);
  assertEquals(payload.excluded, []);
  assertEquals(payload.predictions[1].data_quality_status, "WARN");
  assertEquals(payload.predictions[1].data_quality_hard_fail, false);
  assertEquals(payload.predictions[1].decision, "NO_TRADE");
});

Deno.test("an unmarked database quality failure remains excluded", async () => {
  const rows = snapshotRows();
  rows.audits = [];

  const response = await handler(rows)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
    ),
  );
  const payload = await response.json();
  assertEquals(response.status, 200);
  assertEquals(payload.predictions.length, 1);
  assertEquals(payload.excluded.length, 1);
  assertEquals(payload.excluded[0].symbol, "9999");
  assertEquals(payload.excluded[0].data_quality_hard_fail, true);
});

Deno.test("ambiguous validation history is not attached to a snapshot", async () => {
  const rows = snapshotRows();
  rows.validationLinkStatus = "AMBIGUOUS";
  rows.validationRun = null;
  rows.validationMetrics = [];
  rows.backtests = [];

  const response = await handler(rows)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
    ),
  );
  const payload = await response.json();
  assertEquals(response.status, 200);
  assertEquals(payload.validation, {});
  assert(
    payload.reason_codes.includes("VALIDATION_SNAPSHOT_NOT_LINKED"),
    "ambiguous validation rows must be omitted and disclosed",
  );
});

Deno.test("CORS configuration rejects wildcard or path-based origins", () => {
  for (const value of ["*", "https://alpha.example/path"]) {
    let error: unknown = null;
    try {
      parseAllowedOrigins(value);
    } catch (caught) {
      error = caught;
    }
    assert(error instanceof Error, `invalid origin ${value} must be rejected`);
  }
});
