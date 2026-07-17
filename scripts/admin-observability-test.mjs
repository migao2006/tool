import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

const [migration, modelMigration, releaseMigration, repairMigration, specialFormsMigration, admin, adminHtml, sharedSource, modelSource, policySource] = await Promise.all([
  readFile(new URL("../supabase/migrations/20260716142257_harden_admin_operations_observability.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260716180952_add_v20_model_admin_observability.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260717090140_register_v20_2_model_release.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260717183500_secure_fugle_and_repair_v20_observability.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260717190000_fix_v20_admin_log_special_forms.sql", import.meta.url), "utf8"),
  readFile(new URL("../public/admin.js", import.meta.url), "utf8"),
  readFile(new URL("../public/admin.html", import.meta.url), "utf8"),
  readFile(new URL("../api/v20/_shared.js", import.meta.url), "utf8"),
  readFile(new URL("../supabase/functions/_shared/v20-model.js", import.meta.url), "utf8"),
  readFile(new URL("../supabase/functions/_shared/v20-opportunity-policy.js", import.meta.url), "utf8"),
]);

assert.match(repairMigration,
  /revoke all on function public\.twss_v20_internal_provider_config\(\)[\s\S]*from public, anon, authenticated;[\s\S]*to service_role;/,
  "the decrypted Fugle Vault boundary must remain service-role-only");
assert.match(repairMigration, /from public\.v20_publication_head h[\s\S]*r\.model_version/,
  "global refresh must target the active immutable publication model instead of hardcoded 20.0");
assert.match(repairMigration, /'status', 'success', 'progress', 100/,
  "completed administrator jobs must not remain pending");
assert.match(repairMigration, /\{version\}', '\"20\.2\.1\"'::jsonb/);
assert.doesNotMatch(repairMigration, /pg_catalog\.(?:greatest|least)\(/,
  "LEAST/GREATEST are PostgreSQL special forms and must not be schema-qualified");
assert.match(specialFormsMigration, /pg_get_functiondef/,
  "installed function bodies must receive the same special-form repair");

assert.match(
  migration,
  /revoke all on function public\.twss_v20_persist_global_context\(text, jsonb, jsonb, text\[\]\)[\s\S]*from public, anon, authenticated;[\s\S]*grant execute[\s\S]*to service_role;/,
  "the privileged global-context writer must only be executable by service_role",
);
assert.match(migration, /if \(select auth\.uid\(\)\) is null or not \(select public\.twss_is_admin\(\)\)/);
assert.match(migration, /'finmind_primary'::text, 'primary'::text, 600::integer/);
assert.match(migration, /'finmind_secondary'::text, 'secondary'::text, 600::integer/);
assert.match(migration, /'combined'[\s\S]*v_quota_combined/);
for (const field of [
  "expiredLeases", "staleLeases", "perMinuteLast60", "workerThroughput", "calibrationReadiness",
]) {
  assert.match(migration, new RegExp(`'${field}'`), `admin payload must include ${field}`);
}
assert.match(migration, /'thresholds', pg_catalog\.jsonb_build_object\('exact', 60, 'fallback', 150\)/);
assert.match(
  migration,
  /revoke all on function public\.twss_admin_operations_log\(integer\)[\s\S]*from public, anon, authenticated;[\s\S]*to authenticated, service_role;/,
);

assert.match(modelMigration, /public\.twss_v20_register_model_release/);
assert.match(modelMigration, /'modelVersion', '20\.1'/);
const canonicalSource = (source) => source.replace(/\r\n?/g, "\n");
const artifactHash = createHash("sha256")
  .update(canonicalSource(modelSource))
  .update(canonicalSource(policySource))
  .digest("hex");
assert.match(modelMigration, /'artifactHash', '441cc454b03e7d689b1c5f7df71420afd7ec49ad60960286d9e349f19e286689'/,
  "the historical v20.1 release identity must remain immutable");
assert.match(releaseMigration, /'modelVersion', '20\.2'/);
assert.match(releaseMigration, new RegExp(`'artifactHash', '${artifactHash}'`),
  "the v20.2 release hash must match the deployable model bundle");
assert.match(releaseMigration, /'performanceStatus', 'collecting'/,
  "the correctness patch must not claim forward performance");
assert.match(releaseMigration, /twss_v20_set_model_channel[\s\S]*'challenger'[\s\S]*twss_v20_promote_challenger/,
  "v20.2 must pass through the auditable challenger channel before promotion");
const artifactIdentitySource = await readFile(
  new URL("../supabase/functions/_shared/v20-model-artifact.js", import.meta.url),
  "utf8",
);
const appVersion = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8")).version;
assert.match(artifactIdentitySource, new RegExp(`V20_MODEL_ARTIFACT_HASH = "${artifactHash}"`),
  "the Edge worker must publish the exact registered model bundle identity");
assert.match(modelMigration, /'engine', 'transparent_rule_baseline'/);
assert.match(modelMigration, /'performanceStatus', 'collecting'/);
assert.match(modelMigration, /'performanceMetricsAvailable', false/);
assert.match(modelMigration, /'sampleCount', 0,[\s\S]*'minimumSampleCount', 100/);
assert.match(modelMigration, /'channel', 'champion'/);
assert.match(modelMigration, /where r\.id = v_release_id[\s\S]*r\.validation_status = 'passed'/,
  "the baseline may only fill an empty champion channel after structural validation passes");
assert.match(modelMigration, /if \(select auth\.uid\(\)\) is null or not \(select public\.twss_is_admin\(\)\)/);
for (const field of [
  "modelObservability", "currentPublication", "channels", "runtimeByModel", "validation",
  "rankChanges", "anomalies", "averageEstimatedCostPct", "averageTurnoverProxy",
  "publicItemCoveragePct", "pendingOutcomeCount",
]) {
  assert.match(modelMigration, new RegExp(`'${field}'`), `v20.1 admin payload must include ${field}`);
}
assert.match(
  modelMigration,
  /'calibrationReadiness'[\s\S]*'thresholds', pg_catalog\.jsonb_build_object\('exact', 100, 'fallback', 150\)/,
  "v20.1 must override the historical exact calibration threshold with 100 samples",
);
assert.match(
  modelMigration,
  /revoke all on function public\.twss_admin_operations_log_v210_base\(integer\)[\s\S]*from public, anon, authenticated;[\s\S]*to service_role;/,
  "the prior privileged payload must become service-only",
);
assert.match(
  modelMigration,
  /revoke all on function public\.twss_admin_operations_log\(integer\)[\s\S]*from public, anon, authenticated;[\s\S]*to authenticated, service_role;/,
  "only authenticated administrators may call the public operations RPC",
);
assert.doesNotMatch(modelMigration, /average(?:Net|Gross|Excess)Return|winRate|hitRate/i,
  "collecting-only observability must not publish synthetic performance values");

for (const label of [
  "第一組", "第二組", "兩組合計", "過期租約", "心跳逾時", "Worker 處理速度", "模型校準成熟度",
]) {
  assert.match(admin, new RegExp(label), `admin UI must show ${label}`);
}
assert.match(admin, /primaryQuota\.usedLast60Minutes/);
assert.match(admin, /secondaryQuota\.usedLast60Minutes/);
assert.match(admin, /combinedQuota\.usedLast60Minutes/);
for (const label of [
  "模型 Champion／Challenger", "短波段平均成本", "中期平均成本", "樣本收集中",
  "異常股票", "排名比較", "換手代理",
]) {
  assert.match(admin, new RegExp(label), `admin UI must show ${label}`);
}
assert.match(admin, /calibration\.thresholds\?\.exact \?\? 100/);
assert.match(admin, /const modelObservability = payload\.modelObservability \|\| \{\}/,
  "missing observability data must degrade safely");
assert.match(admin, /if \(!channel \|\| typeof channel !== 'object'\)/,
  "an unconfigured Champion or Challenger must render a safe empty state");
assert.match(adminHtml, new RegExp(`admin\\.js\\?v=${appVersion.replaceAll(".", "\\.")}`));
assert.match(adminHtml, new RegExp(`styles\\.css\\?v=${appVersion.replaceAll(".", "\\.")}`));

assert.match(sharedSource, /JSON\.stringify\(\{ service: "twss-v20-api", \.\.\.payload \}\)/);
assert.match(sharedSource, /msg: "start"/);
assert.match(sharedSource, /msg: "done"/);
assert.match(sharedSource, /msg: "failed"/);
assert.doesNotMatch(sharedSource, /msg: "failed"[\s\S]{0,300}(?:error\.message|url[,}])/,
  "failure logs must not record error messages or full URLs that may contain secrets");

const originalLog = console.log;
const originalError = console.error;
const events = [];
console.log = (line) => events.push(String(line));
console.error = (line) => events.push(String(line));
try {
  const shared = await import(`../api/v20/_shared.js?observability=${Date.now()}`);
  const ok = await shared.handleV20(
    new Request("https://app.test/api/v20/home?token=must-not-appear", {
      headers: { "x-vercel-id": "hkg1::safe-request" },
    }),
    async () => ({ ok: true }),
  );
  assert.equal(ok.status, 200);

  const failed = await shared.handleV20(
    new Request("https://app.test/api/v20/home?secret=must-not-appear"),
    async () => { throw new Error("private-token-must-not-appear"); },
  );
  assert.equal(failed.status, 503);
} finally {
  console.log = originalLog;
  console.error = originalError;
}

const parsedEvents = events.map((line) => JSON.parse(line));
assert.equal(parsedEvents.filter((event) => event.msg === "start").length, 2);
assert.equal(parsedEvents.filter((event) => event.msg === "done").length, 1);
assert.equal(parsedEvents.filter((event) => event.msg === "failed").length, 1);
assert.ok(parsedEvents.every((event) => event.route === "/api/v20/home"));
assert.ok(events.every((line) => !/must-not-appear|private-token/.test(line)));

console.log("Admin security and observability tests passed");
