import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { readFile } from "node:fs/promises";
import maintenanceGate, {
  maintenanceGateInternals,
  resetMaintenanceCacheForTest,
} from "../middleware.js";
import {
  maintenanceDisposition,
  maintenanceSkipPayload,
} from "../supabase/functions/_shared/maintenance-guard.js";

const variables = [
  "MAINTENANCE_MODE",
  "MAINTENANCE_FAIL_CLOSED",
  "MAINTENANCE_BYPASS_SECRET",
  "VERCEL_ENV",
  "MARKET_SUPABASE_URL",
  "SUPABASE_URL",
  "MARKET_SUPABASE_SERVICE_ROLE_KEY",
  "SUPABASE_SERVICE_ROLE_KEY",
  "MARKET_SUPABASE_PUBLISHABLE_KEY",
  "SUPABASE_PUBLISHABLE_KEY",
  "SUPABASE_ANON_KEY",
];
const original = Object.fromEntries(variables.map((name) => [name, process.env[name]]));
const originalFetch = globalThis.fetch;

function clearEnvironment() {
  for (const name of variables) delete process.env[name];
  resetMaintenanceCacheForTest();
}

try {
  clearEnvironment();
  process.env.MAINTENANCE_MODE = "1";

  const apiResponse = await maintenanceGate(new Request("https://smart.example/api/v20/home", {
    headers: { accept: "application/json" },
  }));
  assert.equal(apiResponse.status, 503);
  assert.equal(apiResponse.headers.get("cache-control"), "no-store, no-cache, max-age=0, must-revalidate");
  assert.equal(apiResponse.headers.get("retry-after"), "300");
  assert.deepEqual(await apiResponse.json(), {
    ok: false,
    code: "MAINTENANCE",
    message: "系統正在安全升級，完成驗證後將恢復服務。",
    phase: "maintenance",
    generation: null,
    updatedAt: null,
  });

  const pageResponse = await maintenanceGate(new Request("https://smart.example/", {
    headers: { accept: "text/html" },
  }));
  assert.equal(pageResponse.status, 503);
  assert.match(await pageResponse.text(), /系統安全升級中/);

  process.env.MAINTENANCE_BYPASS_SECRET = "unit-test-bypass-secret";
  const timestamp = String(Date.now());
  const signature = createHmac("sha256", process.env.MAINTENANCE_BYPASS_SECRET)
    .update(`${timestamp}\nGET\n/api/health`)
    .digest("hex");
  const bypassResponse = await maintenanceGate(new Request("https://smart.example/api/health", {
    headers: {
      "x-maintenance-timestamp": timestamp,
      "x-maintenance-signature": signature,
    },
  }));
  assert.equal(bypassResponse.headers.get("x-middleware-next"), "1");

  const invalidBypass = await maintenanceGate(new Request("https://smart.example/api/v20/home", {
    headers: {
      "x-maintenance-timestamp": timestamp,
      "x-maintenance-signature": signature,
    },
  }));
  assert.equal(invalidBypass.status, 503, "a signed health token must not bypass application routes");

  const verifySignature = createHmac("sha256", process.env.MAINTENANCE_BYPASS_SECRET)
    .update(`${timestamp}\nVERIFY\nGET`)
    .digest("hex");
  assert.equal(await maintenanceGateInternals.hasSignedBypass(
    new Request("https://smart.example/api/v20/rankings?model=short", {
      headers: {
        "x-maintenance-timestamp": timestamp,
        "x-maintenance-signature": verifySignature,
        "x-maintenance-scope": "verify-get",
      },
    }),
    new URL("https://smart.example/api/v20/rankings?model=short"),
    { enabled: true, phase: "verifying" },
  ), true, "signed verification may read the full release while the public gate stays closed");
  assert.equal(await maintenanceGateInternals.hasSignedBypass(
    new Request("https://smart.example/api/v20/rankings", {
      method: "POST",
      headers: {
        "x-maintenance-timestamp": timestamp,
        "x-maintenance-signature": verifySignature,
        "x-maintenance-scope": "verify-get",
      },
    }),
    new URL("https://smart.example/api/v20/rankings"),
    { enabled: true, phase: "verifying" },
  ), false, "verification bypass is read-only");

  clearEnvironment();
  let publicStatusRequest = null;
  globalThis.fetch = async (input, init = {}) => {
    publicStatusRequest = { url: String(input), init };
    return Response.json([]);
  };
  const defaultClosedResponse = await maintenanceGate(new Request("https://smart.example/"));
  assert.equal(defaultClosedResponse.status, 503, "missing maintenance state must fail closed by default");
  assert.equal(
    publicStatusRequest?.url,
    "https://lfkdkdyaatdlizryiyon.supabase.co/rest/v1/rpc/twss_public_maintenance_status",
    "an environment-free deployment must use the fixed MARKET public maintenance RPC",
  );
  assert.equal(publicStatusRequest?.init?.method, "POST");
  assert.equal(publicStatusRequest?.init?.body, "{}");
  assert.equal(publicStatusRequest?.init?.headers?.apikey, "sb_publishable_r3h9eQIYdIqScvmc77avAg_OLgBT6lh");
  assert.equal(publicStatusRequest?.init?.headers?.["content-type"], "application/json");
  assert.equal(publicStatusRequest?.init?.headers?.authorization, undefined,
    "opaque Supabase publishable keys must never be sent as bearer JWTs");

  process.env.MAINTENANCE_FAIL_CLOSED = "false";
  resetMaintenanceCacheForTest();
  const explicitOpenResponse = await maintenanceGate(new Request("https://smart.example/"));
  assert.equal(explicitOpenResponse.headers.get("x-middleware-next"), "1",
    "only an explicit false opt-out may fail open");

  process.env.MAINTENANCE_FAIL_CLOSED = "true";
  resetMaintenanceCacheForTest();
  const closedResponse = await maintenanceGate(new Request("https://smart.example/api/v20/home"));
  assert.equal(closedResponse.status, 503, "maintenance can explicitly fail closed when status is unavailable");

  clearEnvironment();
  globalThis.fetch = async () => Response.json({
    enabled: true,
    phase: "maintenance",
    generation: 11,
    updatedAt: "2026-07-17T01:02:03Z",
  });
  const publicRpcMaintenance = await maintenanceGate(new Request("https://smart.example/"));
  assert.equal(publicRpcMaintenance.status, 503);
  assert.equal(publicRpcMaintenance.headers.get("x-maintenance-phase"), "maintenance");
  assert.match(await publicRpcMaintenance.text(), /系統安全升級中/);

  clearEnvironment();
  globalThis.fetch = async () => Response.json({
    enabled: false,
    phase: "off",
    generation: 12,
    updatedAt: "2026-07-17T01:03:04Z",
  });
  const publicRpcOpen = await maintenanceGate(new Request("https://smart.example/"));
  assert.equal(publicRpcOpen.headers.get("x-middleware-next"), "1");

  clearEnvironment();
  globalThis.fetch = async () => Response.json({ enabled: "false", phase: "off" });
  const invalidPublicStatus = await maintenanceGate(new Request("https://smart.example/"));
  assert.equal(invalidPublicStatus.status, 503,
    "an invalid public maintenance payload must fail closed rather than coercing values");

  assert.throws(() => maintenanceGateInternals.normalizeMaintenanceState([]), /missing or invalid/);
  assert.throws(() => maintenanceGateInternals.normalizeMaintenanceState({ enabled: "false" }), /missing or invalid/);
  assert.deepEqual(maintenanceGateInternals.normalizeMaintenanceState({
    enabled: true,
    phase: "verifying",
    generation: "13",
    updatedAt: "2026-07-17T01:04:05Z",
  }), {
    enabled: true,
    phase: "verifying",
    reason: null,
    generation: 13,
    updated_at: "2026-07-17T01:04:05Z",
  });

  assert.deepEqual(maintenanceGateInternals.supabaseHeaders("sb_secret_unit-test"), {
    apikey: "sb_secret_unit-test",
    accept: "application/json",
  }, "new Supabase secret keys must never be sent as bearer JWTs");
  assert.deepEqual(maintenanceGateInternals.supabaseHeaders("sb_publishable_unit-test"), {
    apikey: "sb_publishable_unit-test",
    accept: "application/json",
  }, "new Supabase publishable keys must never be sent as bearer JWTs");
  assert.deepEqual(maintenanceGateInternals.supabaseHeaders("legacy-service-role-jwt"), {
    apikey: "legacy-service-role-jwt",
    authorization: "Bearer legacy-service-role-jwt",
    accept: "application/json",
  });

  const sql = await readFile(
    new URL("../supabase/migrations/20260716174105_operational_maintenance_control.sql", import.meta.url),
    "utf8",
  );
  assert.match(sql, /twss_maintenance_enable_web/);
  assert.match(sql, /twss_maintenance_pause_jobs/);
  assert.match(sql, /twss_maintenance_open_web/);
  assert.match(sql, /twss_maintenance_reclose_web/);
  assert.match(sql, /twss_maintenance_resume_jobs/);
  assert.match(sql, /cron\.alter_job\(v_job\.jobid, active => false\)/);
  assert.match(sql, /cron_snapshot/);
  assert.match(sql, /cron_snapshot = v_current_snapshot \|\| cron_snapshot/,
    "re-pausing must preserve the original active state while capturing new cron jobs");
  assert.match(sql, /twss_maintenance_events_append_only/);
  assert.match(sql, /maintenance_events_are_append_only/);
  assert.match(sql, /'global', true, 'draining', 'initial v20\.1 verified rollout'/,
    "the initial production rollout must start behind the database-backed maintenance gate");
  assert.match(sql, /v_control\.enabled and v_control\.phase in \('draining', 'maintenance'\)/,
    "entering maintenance must be safely retryable without overwriting the cron snapshot");
  assert.match(sql, /set enabled = true,\s*phase = 'verifying'/,
    "the public gate must stay closed during signed smoke verification");
  assert.match(sql, /set enabled = false,\s*phase = 'off'/,
    "the public gate opens only when the exact cron state is restored");
  assert.doesNotMatch(sql, /pg_catalog\.(?:coalesce|nullif|greatest|least)\s*\(/,
    "Postgres special SQL forms cannot be schema-qualified");
  assert.doesNotMatch(sql, /grant execute[\s\S]{0,160}to (anon|authenticated)/i);

  const publicStatusSql = await readFile(
    new URL("../supabase/migrations/20260716185500_add_public_maintenance_status.sql", import.meta.url),
    "utf8",
  );
  assert.match(publicStatusSql, /create or replace function public\.twss_public_maintenance_status\(\)/);
  assert.match(publicStatusSql, /security definer/);
  assert.match(publicStatusSql, /grant execute[\s\S]{0,120}to anon, authenticated, service_role/);
  const publicStatusBody = publicStatusSql.match(/as \$function\$([\s\S]*?)\$function\$/)?.[1] || "";
  assert.doesNotMatch(publicStatusBody, /'reason'|'actor'|cron_snapshot/,
    "the public maintenance read model must expose only non-sensitive gate state");

  assert.deepEqual(await maintenanceDisposition(async () => ({ data: true })), {
    blocked: true,
    status: 202,
    reason: "maintenance",
  });
  assert.deepEqual(await maintenanceDisposition(async () => ({ data: false })), {
    blocked: false,
    status: 200,
    reason: null,
  });
  const unavailable = await maintenanceDisposition(async () => {
    throw new Error("database unavailable");
  });
  assert.equal(unavailable.blocked, true);
  assert.equal(unavailable.status, 503);
  assert.deepEqual(maintenanceSkipPayload(unavailable), {
    ok: false,
    status: "skipped",
    reason: "maintenance_guard_unavailable",
  });

  const guardedSources = await Promise.all([
    "twss-v20-model/index.ts",
    "twss-sync-batch/index.ts",
    "twss-v19-news/index.ts",
    "twss-ai-research/index.ts",
  ].map((file) => readFile(new URL(`../supabase/functions/${file}`, import.meta.url), "utf8")));
  guardedSources.forEach((source) => assert.match(source, /maintenanceDisposition\(rest\)/));

  console.log("Maintenance gate tests passed");
} finally {
  globalThis.fetch = originalFetch;
  clearEnvironment();
  for (const [name, value] of Object.entries(original)) {
    if (value !== undefined) process.env[name] = value;
  }
}
