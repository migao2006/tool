import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const [migration, admin, adminHtml, sharedSource] = await Promise.all([
  readFile(new URL("../supabase/migrations/20260716142257_harden_admin_operations_observability.sql", import.meta.url), "utf8"),
  readFile(new URL("../public/admin.js", import.meta.url), "utf8"),
  readFile(new URL("../public/admin.html", import.meta.url), "utf8"),
  readFile(new URL("../api/v20/_shared.js", import.meta.url), "utf8"),
]);

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

for (const label of [
  "第一組", "第二組", "兩組合計", "過期租約", "心跳逾時", "Worker 處理速度", "模型校準成熟度",
]) {
  assert.match(admin, new RegExp(label), `admin UI must show ${label}`);
}
assert.match(admin, /primaryQuota\.usedLast60Minutes/);
assert.match(admin, /secondaryQuota\.usedLast60Minutes/);
assert.match(admin, /combinedQuota\.usedLast60Minutes/);
assert.match(adminHtml, /admin\.js\?v=20\.0\.7/);

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
