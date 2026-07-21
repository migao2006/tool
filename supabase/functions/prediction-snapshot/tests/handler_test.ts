import { parseAllowedOrigins } from "../cors.ts";
import { createHandler } from "../handler.ts";
import type {
  MarketScope,
  SnapshotRepositoryContract,
  SnapshotRows,
} from "../types.ts";
import { assert, assertEquals } from "./assertions.ts";
import { snapshotRows } from "./fixtures.ts";

class FakeRepository implements SnapshotRepositoryContract {
  constructor(
    readonly rows: SnapshotRows | null,
    readonly expectedMarket: MarketScope = "TWSE",
  ) {}
  loadLatest(
    horizon: number,
    marketScope: MarketScope,
  ): Promise<SnapshotRows | null> {
    assertEquals(horizon, 5);
    assertEquals(marketScope, this.expectedMarket);
    return Promise.resolve(this.rows);
  }
}

function handler(
  rows: SnapshotRows | null,
  expectedMarket: MarketScope = "TWSE",
) {
  return createHandler({
    repository: new FakeRepository(rows, expectedMarket),
    corsPolicy: parseAllowedOrigins(
      "https://alpha.example,http://127.0.0.1:3000",
    ),
    now: () => new Date("2026-07-17T07:00:00+00:00"),
  });
}

function gatedResearchRows(): SnapshotRows {
  const rows = snapshotRows();
  const snapshotSha256 = "a".repeat(64);
  rows.run.candidate_count = 0;
  rows.run.no_trade_count = 1;
  rows.run.hard_fail_count = 0;
  rows.run.source_dates = {
    ...rows.run.source_dates,
    snapshot_sha256: snapshotSha256,
    decision_gate_count: 8,
    decision_gate_attachment_contract: "research-decision-gate.v1",
  };
  rows.predictions = [rows.predictions[1]];
  rows.audits = [];
  const gateNames = [
    "data_quality_hard_gate",
    "tradability_gate",
    "liquidity_capacity_gate",
    "market_exposure_cap",
    "calibrated_direction_probabilities",
    "net_quantile_thresholds",
    "rank_eligibility",
    "position_capacity_limits",
  ];
  rows.gates = gateNames.map((gateName, index) => ({
    stock_prediction_id: 12,
    gate_order: index + 1,
    gate_name: gateName,
    passed: index === 2,
    actual_value: {
      contract_version: "research-decision-gate.v1",
      value: index === 2 ? { adv20_ntd: 1_000_000_000 } : "MISSING",
      source_date: index === 2 ? "2026-07-17" : null,
      attachment_snapshot_sha256: snapshotSha256,
    },
    threshold_value: { configured: true },
    reason_code: index === 2 ? "PASS" : "FORMAL_INPUT_MISSING",
  }));
  return rows;
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
  assertEquals(payload.market_scope, "TWSE");
  assertEquals(payload.as_of_date, null);
  assertEquals(payload.predictions, []);
});

Deno.test("TPEX empty snapshots do not fall back to TWSE", async () => {
  const response = await handler(null, "TPEX")(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5&market=TPEX",
    ),
  );
  const payload = await response.json();
  assertEquals(response.status, 200);
  assertEquals(payload.market_scope, "TPEX");
  assertEquals(payload.predictions, []);
  assertEquals(payload.reason_codes, ["NO_PREDICTION_SNAPSHOT"]);
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

Deno.test("market defaults to TWSE and rejects ALL or unknown scopes", async () => {
  const defaultMarket = await handler(null)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
    ),
  );
  assertEquals(defaultMarket.status, 200);
  assertEquals((await defaultMarket.json()).market_scope, "TWSE");

  for (const market of ["ALL", "OTC", "unknown", ""]) {
    const response = await handler(null)(
      new Request(
        `https://api.example/functions/v1/prediction-snapshot?horizon=5&market=${market}`,
      ),
    );
    assertEquals(response.status, 422);
    assertEquals((await response.json()).code, "UNSUPPORTED_MARKET");
  }
});

Deno.test("cross-market rows fail with a conflict", async () => {
  const rows = snapshotRows();
  rows.predictions[0].market = "TPEX";
  const response = await handler(rows)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5&market=TWSE",
    ),
  );
  assertEquals(response.status, 409);
  assertEquals(
    (await response.json()).code,
    "PREDICTION_MARKET_SCOPE_MISMATCH",
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

Deno.test("research gate envelopes expose source dates and hide obsolete markers", async () => {
  const rows = gatedResearchRows();
  rows.predictions[0].reason_codes = [
    "RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY",
    "RESEARCH_DATA_QUALITY_WARN",
  ];

  const response = await handler(rows)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
    ),
  );
  const payload = await response.json();
  const prediction = payload.predictions.find((value: { symbol: string }) =>
    value.symbol === "9999"
  );

  assertEquals(response.status, 200);
  assertEquals(prediction.gates.length, 8);
  assertEquals(prediction.gates[2].source_date, "2026-07-17");
  assertEquals(prediction.gates[2].actual.adv20_ntd, 1_000_000_000);
  assertEquals(prediction.gates[1].source_date, null);
  assertEquals(
    prediction.reason_codes.includes("RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY"),
    false,
  );
});

Deno.test("an incomplete research gate attachment fails closed", async () => {
  const rows = gatedResearchRows();
  rows.gates.pop();

  const response = await handler(rows)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
    ),
  );
  const payload = await response.json();

  assertEquals(response.status, 409);
  assertEquals(payload.code, "RESEARCH_DECISION_GATE_ATTACHMENT_INCOMPLETE");
});

Deno.test("a research gate from another snapshot fails closed", async () => {
  const rows = gatedResearchRows();
  rows.gates[0].actual_value = {
    contract_version: "research-decision-gate.v1",
    value: "MISSING",
    source_date: null,
    attachment_snapshot_sha256: "b".repeat(64),
  };

  const response = await handler(rows)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
    ),
  );
  const payload = await response.json();

  assertEquals(response.status, 409);
  assertEquals(payload.code, "RESEARCH_DECISION_GATE_ATTACHMENT_MISMATCH");
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

Deno.test("current industry classification respects the half-open effective interval", async () => {
  const expiredRows = snapshotRows();
  expiredRows.currentSecurityHistory = [{
    security_id: 101,
    effective_from: "2026-07-01",
    effective_to: "2026-07-17",
    industry_code: "24",
    industry_name: "半導體業",
    source_version: "fixture-v1",
    available_at: "2026-07-01T00:00:00+00:00",
  }];

  const expiredResponse = await handler(expiredRows)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
    ),
  );
  const expiredPayload = await expiredResponse.json();
  assertEquals(expiredResponse.status, 200);
  assertEquals(
    expiredPayload.predictions[0].industry_classification_effective_from,
    null,
  );
  assertEquals(
    expiredPayload.predictions[0].industry_classification_effective_to,
    null,
  );

  const activeRows = snapshotRows();
  activeRows.currentSecurityHistory = [{
    security_id: 101,
    effective_from: "2026-07-01",
    effective_to: "2026-07-18",
    industry_code: "24",
    industry_name: "半導體業",
    source_version: "fixture-v1",
    available_at: "2026-07-01T00:00:00+00:00",
  }];
  const activeResponse = await handler(activeRows)(
    new Request(
      "https://api.example/functions/v1/prediction-snapshot?horizon=5",
    ),
  );
  const activePayload = await activeResponse.json();
  assertEquals(activeResponse.status, 200);
  assertEquals(
    activePayload.predictions[0].industry_classification_effective_from,
    "2026-07-01",
  );
  assertEquals(
    activePayload.predictions[0].industry_classification_effective_to,
    "2026-07-18",
  );
});
