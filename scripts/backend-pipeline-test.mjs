import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const [sync, schema, grants, cron, trim, config] = await Promise.all([
  readFile(new URL("../supabase/functions/twss-sync-batch/index.ts", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714090000_add_persistent_stock_backend.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714090500_harden_stock_backend_grants.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714091000_schedule_persistent_stock_sync.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714091500_trim_analysis_cache_payloads.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/config.toml", import.meta.url), "utf8"),
]);

assert.match(sync, /Math\.min\(3, Number\(requestedLimit\) \|\| 2\)/, "batch size must stay bounded");
assert.match(sync, /cursor_offset: processed/, "successful batches must persist their verified count");
assert.match(sync, /const missing = refs\.filter/, "newly discovered symbols must be processed before refreshes");
assert.match(sync, /analysis_version === ANALYSIS_VERSION/, "a new analysis version must trigger revalidation");
assert.doesNotMatch(sync.match(/function compactDeep[\s\S]*?\n}/)?.[0] || "", /priceHistory:/, "rank caches must not duplicate price history");
assert.match(sync, /row\[key\] === undefined \? null : row\[key\]/, "bulk rows must preserve missing values as null");
assert.match(sync, /for \(const row of rows\)/, "a failed symbol must not cancel sibling symbols");
assert.match(sync, /x-twss-sync-token/);
assert.doesNotMatch(sync, /sb_secret_[A-Za-z0-9_-]{8,}/, "server secrets must not exist in source");

for (const table of [
  "stock_price_history", "stock_monthly_revenues", "stock_quarterly_financials",
  "stock_institutional_flows", "stock_margin_history", "stock_analysis_cache",
  "opportunity_score_history", "stock_sync_state",
]) {
  assert.match(schema, new RegExp(`alter table public\\.${table} enable row level security`));
}
assert.match(schema, /vault\.create_secret/);
assert.match(schema, /revoke all on function public\.twss_verify_sync_token/);
assert.match(grants, /revoke all on[\s\S]*from anon, authenticated/);
assert.match(grants, /grant select on[\s\S]*to anon, authenticated/);

assert.match(cron, /"group":"listed","limit":2/);
assert.match(cron, /"group":"otc","limit":2/);
assert.match(cron, /"group":"etf","limit":2/);
assert.match(config, /verify_jwt = false/);
assert.match(config, /entrypoint = "\.\/functions\/twss-sync-batch\/index\.ts"/);
assert.match(trim, /analysis - 'priceHistory'/);

console.log("Backend pipeline tests passed: bounded cursors, three schedules, Vault auth, RLS, and read-only grants");
