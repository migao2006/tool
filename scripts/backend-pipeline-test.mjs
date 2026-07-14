import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const [sync, baseSchema, schema, grants, cron, acceleratedCron, leases, quota, publicHistoryQuota, preserve, repairQueue, clearEtfRepairs, etfDirectionRepair, lateCoverageRepair, clearOldVersionRepairs, trim, config, marketHandler, workflow, exporter, backtest] = await Promise.all([
  readFile(new URL("../supabase/functions/twss-sync-batch/index.ts", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714040000_base_schema.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714090000_add_persistent_stock_backend.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714090500_harden_stock_backend_grants.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714091000_schedule_persistent_stock_sync.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714134000_ultimate_speed_and_data_repairs.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714134500_sync_leases_retry_retention.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714135000_finmind_sliding_quota.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714183500_harden_public_history_quota.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714135500_preserve_last_good_and_schedule_guard.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714144000_analysis_repair_queue.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714144500_clear_etf_repair_flags.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714162500_repair_etf_direction_classification.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714163500_requeue_late_legacy_financial_coverage.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714164500_clear_incompatible_version_repair_flags.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714091500_trim_analysis_cache_payloads.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/config.toml", import.meta.url), "utf8"),
  readFile(new URL("../src/market-data.js", import.meta.url), "utf8"),
  readFile(new URL("../.github/workflows/update-market-data.yml", import.meta.url), "utf8"),
  readFile(new URL("./export-backend-snapshot.mjs", import.meta.url), "utf8"),
  readFile(new URL("./backtest-snapshots.mjs", import.meta.url), "utf8"),
]);

const [aiEdge, aiShared, aiMigration, aiExpiryPolicy, aiManualMigration, aiUnlimitedMigration] = await Promise.all([
  readFile(new URL("../supabase/functions/twss-ai-research/index.ts", import.meta.url), "utf8"),
  readFile(new URL("../supabase/functions/_shared/ai-research.js", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714213000_add_independent_ai_research.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260714220000_hide_expired_ai_research.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260715070000_manual_ai_research_button.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260715120000_unlimited_manual_ai_research.sql", import.meta.url), "utf8"),
]);
const aiInternalPolicies = await readFile(
  new URL("../supabase/migrations/20260714214500_explicit_ai_internal_policies.sql", import.meta.url),
  "utf8",
);
const aiVaultReader = await readFile(
  new URL("../supabase/migrations/20260715060000_add_vault_gemini_secret_reader.sql", import.meta.url),
  "utf8",
);

assert.match(sync, /FINMIND_AUTHENTICATED \? 22 : 10/, "reused company batches must double throughput inside the same request slice");
assert.match(sync, /FINMIND_AUTHENTICATED \? 23 : 19/, "ETF batches must use their fair rolling-hour slice");
assert.match(sync, /twss_reserve_api_batch/, "every persistent batch must reserve the shared FinMind budget");
assert.match(sync, /return 4 \+ \(reusableRevenue \? 0 : 1\) \+ \(reusableFinancial \? 0 : 3\)/, "request cost must reflect reusable history");
assert.match(sync, /cursor_offset: processed/, "successful batches must persist their verified count");
assert.match(sync, /const allMissing = refs\.filter/, "newly discovered symbols must be processed before refreshes");
assert.match(sync, /const dueRepairs = refs\.filter/, "ready rows with an empty essential source must re-enter the repair queue");
assert.match(sync, /financialCoverage\.cashflowRows/, "financial reuse must require verified cash-flow coverage");
assert.match(sync, /finite\(stock\.revenueLastYearMonth\).*Number\(stock\.revenueLastYearMonth\) === 0/s, "null prior-year revenue must not be treated as zero");
assert.match(sync, /analysis_version === ANALYSIS_VERSION/, "a new analysis version must trigger revalidation");
assert.match(sync, /row\.status === "ready"/, "failed analyses must not be mistaken for verified candidates");
assert.match(sync, /finmindRetries: 0/, "scheduled batches must defer retries to later runs to keep the hourly cap exact");
assert.match(sync, /twss_claim_sync_lease/, "scheduled batches must use a distributed lease");
assert.match(sync, /next_retry_at/, "failed symbols must use persisted retry backoff");
assert.match(sync, /previous\?\.status === "ready"/, "a refresh failure must preserve the last-known-good analysis");
assert.match(sync, /currentQuote: stock/, "same-day official quotes must close the historical provider lag");
assert.match(sync, /serveOnDemandHistory/, "missing per-symbol history must use the persistent on-demand path");
assert.match(sync, /reserveFinmindBatch\(\[1\], 0, 1/, "on-demand history must reserve exactly one shared API unit");
assert.match(sync, /buildPriceHistory[\s\S]*finmindRetries: 0/, "a one-unit reservation must not hide in-request FinMind retries");
assert.match(sync, /stock_price_history[\s\S]*symbol,trade_date/, "on-demand history must be persisted for later requests");
assert.match(sync, /HISTORY_PENDING/, "a full hourly budget must return a structured pending state");
assert.match(sync, /claimLease\(jobKey, owner, 180\)/, "concurrent opens of one symbol must share a distributed lease");
assert.match(sync, /existing\.length >= 120/, "a partial series must not be mistaken for complete technical history");
assert.match(sync, /historyComplete === true/, "a confirmed short source history must not be fetched forever");
assert.match(sync, /mergeLatestOfficialSnapshot/, "on-demand history must merge the latest official daily quote");
assert.match(sync, /bypassCache: true/, "reserved scheduled calls must not be hidden by an eight-hour memory cache");
assert.match(sync, /passesPreflight\(stock, group\)/, "liquidity and hard-risk exclusions must run before expensive history requests");
assert.match(sync, /missingRevenueParams\.set\("raw_data->>revenue", "is\.null"\)/, "the deep queue must identify cross-section revenue gaps explicitly");
assert.match(sync, /const backfillSlots = group === "etf" \? 0 : Math\.max\(1, Math\.ceil\(limit \/ 2\)\)/, "company batches must reserve half their slots for missing-revenue repair");
assert.match(sync, /FINMIND_AUTHENTICATED \? 88 : 50/, "free-level company batches may claim up to 50 calls while the shared ledger enforces 300 per rolling hour");
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
for (const table of ["stock_master", "stock_snapshots"]) {
  assert.match(baseSchema, new RegExp(`alter table public\\.${table} enable row level security`));
  assert.match(baseSchema, new RegExp(`create policy ${table}_public_read`));
}
assert.doesNotMatch(grants, /data_sync_status/, "fresh migrations must not depend on an undefined legacy table");
assert.match(schema, /vault\.create_secret/);
assert.match(schema, /revoke all on function public\.twss_verify_sync_token/);
assert.match(grants, /revoke all on[\s\S]*from anon, authenticated/);
assert.match(grants, /grant select on[\s\S]*to anon, authenticated/);

assert.match(cron, /"group":"listed","limit":2/);
assert.match(cron, /"group":"otc","limit":2/);
assert.match(cron, /"group":"etf","limit":2/);
assert.match(acceleratedCron, /"group":"listed","limit":22/);
assert.match(acceleratedCron, /"group":"otc","limit":22/);
assert.match(acceleratedCron, /"group":"etf","limit":23/);
assert.match(acceleratedCron, /300\/600 calls per 60 minutes/);
assert.match(acceleratedCron, /stock_monthly_revenues/);
assert.match(acceleratedCron, /stock_quarterly_financials/);
assert.match(leases, /lease_until/);
assert.match(leases, /twss_prune_history/);
assert.match(leases, /attempt_count/);
assert.match(leases, /p_seconds integer default 180/);
assert.match(quota, /reserved_at > v_now - interval '60 minutes'/);
assert.match(quota, /pg_advisory_xact_lock/);
assert.match(quota, /revoke all on function public\.twss_reserve_api_batch/);
assert.match(quota, /enable row level security/);
assert.match(publicHistoryQuota, /metadata ->> 'job' = 'public_history'/);
assert.match(publicHistoryQuota, /then 60 else 30/, "interactive repair must have a separate hourly allowance");
assert.match(publicHistoryQuota, /then 20 else 10/, "interactive repair must preserve scheduled-job headroom without blocking near-limit repairs");
assert.match(publicHistoryQuota, /pg_advisory_xact_lock/, "public and scheduled reservations must remain atomic");
assert.match(preserve, /last_attempt_at/);
assert.match(preserve, /'43 6 \* \* 1-5'/);
assert.match(repairQueue, /needs_repair boolean not null default false/);
assert.match(repairQueue, /idx_stock_analysis_cache_repair_queue/);
assert.match(repairQueue, /group_name <> 'etf'/, "the initial repair audit must not enqueue ETF rows for company-only data");
assert.match(clearEtfRepairs, /where group_name = 'etf'/, "the follow-up migration must clear legacy ETF repair flags");
assert.match(clearEtfRepairs, /set needs_repair = false/);
assert.match(etfDirectionRepair, /etf-direction-classification/);
assert.match(etfDirectionRepair, /\{etf,leveraged\}/);
assert.match(etfDirectionRepair, /\{etf,inverse\}/);
assert.match(lateCoverageRepair, /financial-source-coverage/);
assert.match(lateCoverageRepair, /sourceCoverage,incomeRows/);
assert.match(lateCoverageRepair, /analysis_version = '16\.3-ultimate-data-audit'/);
assert.match(clearOldVersionRepairs, /analysis_version <> '16\.3-ultimate-data-audit'/);
assert.match(sync, /repair_reasons.*some[\s\S]*etf-direction-classification/, "one-time migration repairs must not wait six hours");
assert.match(sync, /financial-source-coverage/, "fresh analyses must persist incomplete financial-source coverage as a repair reason");
assert.match(marketHandler, /readBackendAnalysis\(symbol\)/);
assert.doesNotMatch(marketHandler, /payload \|\|= await buildPriceHistory/);
assert.match(workflow, /npm run export-data/);
assert.doesNotMatch(workflow, /npm run update-data/);
assert.match(exporter, /flag: "wx"/, "point-in-time files must be create-only");
assert.match(exporter, /error\?\.code !== "EEXIST"/, "only an existing immutable snapshot may be skipped");
assert.match(exporter, /skippedExistingSnapshot/, "the export must report an immutable-snapshot skip");
assert.match(exporter, /backtestReady/);
assert.match(exporter, /minimumGroupRatio: 0\.75/);
assert.match(backtest, /snapshotCoverage\?\.backtestReady === true/, "partial daily rankings must never enter the point-in-time backtest");
assert.match(config, /verify_jwt = false/);
assert.match(config, /entrypoint = "\.\/functions\/twss-sync-batch\/index\.ts"/);
assert.match(config, /\[functions\.twss-ai-research\][\s\S]*verify_jwt = false/);
assert.match(config, /entrypoint = "\.\/functions\/twss-ai-research\/index\.ts"/);
assert.match(trim, /analysis - 'priceHistory'/);

assert.match(aiMigration, /create table if not exists public\.ai_stock_research/);
assert.match(aiMigration, /create table if not exists public\.ai_research_runs/);
assert.match(aiMigration, /create table if not exists public\.ai_research_usage/);
assert.match(aiMigration, /alter table public\.ai_stock_research enable row level security/);
assert.match(aiMigration, /for select to anon, authenticated using \(status = 'ready'\)/);
assert.match(aiMigration, /grant select \([\s\S]*analysis[\s\S]*\) on public\.ai_stock_research to anon, authenticated/);
assert.match(aiMigration, /twss_reserve_ai_calls/);
assert.match(aiMigration, /greatest\(1, least\(20/);
assert.match(aiMigration, /'20 10 \* \* 1-5'/);
assert.match(aiMigration, /vault\.decrypted_secrets/);
assert.match(aiInternalPolicies, /for all to service_role using \(true\) with check \(true\)/);
assert.doesNotMatch(aiInternalPolicies, /to anon|to authenticated/);
assert.match(aiExpiryPolicy, /expires_at is null or expires_at > now\(\)/);
assert.match(aiExpiryPolicy, /for select to anon, authenticated/);
assert.match(aiExpiryPolicy, /body := '\{\}'::jsonb/);
assert.match(aiManualMigration, /twss_claim_manual_ai_request/);
assert.match(aiManualMigration, /cron\.unschedule/);
assert.match(aiManualMigration, /'mode', 'manual-only'/);
assert.match(aiManualMigration, /to service_role/);
assert.doesNotMatch(aiManualMigration, /grant execute[\s\S]*to anon|grant execute[\s\S]*to authenticated/);
assert.match(aiUnlimitedMigration, /twss-ai-manual-concurrency/);
assert.match(aiUnlimitedMigration, /v_active_count >= 2/);
assert.doesNotMatch(aiUnlimitedMigration, /v_recent_count|twss_reserve_ai_calls|user_limit|global_limit/);
assert.match(aiUnlimitedMigration, /interval '90 days'/);
assert.match(aiUnlimitedMigration, /interval '30 days'/);
assert.match(aiUnlimitedMigration, /'quotaMode', 'unlimited'/);
assert.doesNotMatch(aiUnlimitedMigration, /grant execute[\s\S]*to anon|grant execute[\s\S]*to authenticated/);
assert.match(aiVaultReader, /from vault\.decrypted_secrets/);
assert.match(aiVaultReader, /to service_role/);
assert.doesNotMatch(aiVaultReader, /grant execute[\s\S]*to anon|grant execute[\s\S]*to authenticated/);
assert.match(aiEdge, /x-twss-sync-token/);
assert.match(aiEdge, /GEMINI_API_KEY/);
assert.match(aiEdge, /configured: false/);
assert.match(aiEdge, /selectAiCandidates/);
assert.match(aiEdge, /twss_reserve_ai_calls/);
assert.match(aiEdge, /body\.mode === "manual"/);
assert.match(aiEdge, /verifyUserRequest/);
assert.match(aiEdge, /twss_claim_manual_ai_request/);
assert.doesNotMatch(aiEdge, /opportunity_score_history/);
assert.doesNotMatch(aiEdge, /stock_analysis_cache\?on_conflict/);
assert.match(aiShared, /quantitativeResultReadOnly/);
assert.match(aiShared, /不得覆寫、重算/);
assert.match(marketHandler, /readAiResearch\(symbol\)/);

console.log("Backend pipeline tests passed: bounded cursors, unlimited manual AI concurrency gate, Vault auth, RLS, and read-only grants");
