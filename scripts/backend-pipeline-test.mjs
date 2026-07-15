import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { FINMIND_PROFILES, selectFinmindProfile } from "../src/finmind-profile.js";

const [sync, baseSchema, schema, grants, cron, acceleratedCron, leases, quota, publicHistoryQuota, preserve, repairQueue, clearEtfRepairs, etfDirectionRepair, lateCoverageRepair, clearOldVersionRepairs, trim, config, marketHandler, workflow, exporter, backtest, freeInsights, backtestSchema, hardening, diagnosticPrivacy, adminDashboard, dateReconcile, finmindVault] = await Promise.all([
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
  readFile(new URL("../supabase/migrations/20260715170000_remove_paid_ai_and_add_free_insights.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260715172000_free_backtest_and_missing_data_audit.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260715173000_harden_free_insights_audit.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260715201357_restrict_health_diagnostics_admin_only.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260715205510_add_admin_health_dashboard.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260715210000_add_evening_market_date_reconciliation.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260715235500_secure_finmind_vault.sql", import.meta.url), "utf8"),
]);

const hardenedBacktest = hardening.match(
  /create or replace function public\.twss_evaluate_matured_backtests[\s\S]*?grant execute on function public\.twss_evaluate_matured_backtests/,
)?.[0] || "";
const hardenedHealth = hardening.match(
  /create or replace function public\.twss_public_data_health[\s\S]*?grant execute on function public\.twss_public_data_health/,
)?.[0] || "";
const hardenedMissing = hardening.match(
  /create or replace function public\.twss_public_missing_data[\s\S]*?grant execute on function public\.twss_public_missing_data/,
)?.[0] || "";
const restrictedContext = diagnosticPrivacy.match(
  /create or replace function public\.twss_get_stock_context[\s\S]*?grant execute on function public\.twss_get_stock_context/,
)?.[0] || "";

assert.equal(selectFinmindProfile("   "), FINMIND_PROFILES.public, "blank credentials must stay on the 300/hour profile");
assert.equal(selectFinmindProfile("configured"), FINMIND_PROFILES.authenticated);
assert.equal(FINMIND_PROFILES.authenticated.scheduledClaimPerHour, 597,
  "authenticated cron demand must approach 600/hour while retaining safety headroom");
assert.ok(FINMIND_PROFILES.authenticated.scheduledClaimPerHour <= FINMIND_PROFILES.authenticated.hourlyLimit);
assert.match(sync, /access\.profile\.companyBatchLimit/, "company batches must use the selected FinMind profile");
assert.match(sync, /access\.profile\.etfBatchLimit/, "ETF batches must use the selected FinMind profile");
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
assert.match(sync, /reserveFinmindBatch\(access, \[1\], 0, 1/, "on-demand history must reserve exactly one shared API unit");
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
assert.match(sync, /access\.profile\.companyClaimCap/, "company reservations must use the selected 300\/600 profile");
assert.match(sync, /rpc\/twss_finmind_token/, "the worker must support a service-role Vault fallback");
assert.match(sync, /finmindToken: access\.token/, "the Vault credential must stay in memory and be passed directly to the provider client");
assert.match(sync, /if \(finmindProviderPaused\(error\)\) break/,
  "a global FinMind auth or quota error must stop the remaining symbol batch");
assert.doesNotMatch(sync, /console\.(?:log|info|warn|error)\([^\n]*finmindAccess\.token/i,
  "the resolved FinMind credential must never be logged");
assert.doesNotMatch(sync.match(/function compactDeep[\s\S]*?\n}/)?.[0] || "", /priceHistory:/, "rank caches must not duplicate price history");
assert.match(sync, /row\[key\] === undefined \? null : row\[key\]/, "bulk rows must preserve missing values as null");
assert.match(sync, /for \(const row of rows\)/, "a failed symbol must not cancel sibling symbols");
assert.match(sync, /x-twss-sync-token/);
assert.match(sync, /rpc\/twss_finalize_ranking_cycle/, "a completed deep group must finalize its immutable ranking date");
assert.match(sync, /rpc\/twss_evaluate_matured_backtests/, "completed cycles must evaluate matured results using stored data only");
assert.match(sync, /p_model_version: VERSION/, "ranking finalization must use the frozen score-model version");
assert.match(sync, /const VERSION = "16\.3"/, "the score model version must remain frozen at 16.3");
assert.match(marketHandler, /const VERSION = "17\.2"/, "the public API patch version must match package 17.2");
assert.match(marketHandler, /persistedOtcDate = dateText\(persisted\.date\)/,
  "a persisted TPEx fallback must retain its own trading date");
assert.match(marketHandler, /oldestDate\(effectiveTwsePriceDate, effectiveTpexPriceDate\)/,
  "the all-market watermark must use the conservative common date");
assert.match(marketHandler, /bothMarkets && marketDatesAligned \? "live" : "partial"/,
  "mixed TWSE and TPEx dates must never be labelled as a complete live market");
assert.match(sync, /\[ranking-cycle\] finalization failed/, "ranking finalization failures must remain diagnosable without aborting the data sync");
assert.match(sync, /rankingFinalization/, "the deep job state must retain finalization success or failure diagnostics");
assert.match(sync, /\[admin-data-health\]/, "every protected synchronization run must emit an administrator health summary");
assert.match(sync, /rest\("rpc\/twss_public_data_health"[\s\S]*rest\("rpc\/twss_public_missing_data"/,
  "administrator logs must retain the coverage, repair-queue, and missing-data details removed from the website");
assert.match(sync, /await logAdminHealth\(mode, result/,
  "the protected worker must flush its administrator diagnostics before returning");
assert.doesNotMatch(sync, /sb_secret_[A-Za-z0-9_-]{8,}/, "server secrets must not exist in source");
assert.match(dateReconcile, /twss-universe-evening-reconcile/);
assert.match(dateReconcile, /'10 9,13 \* \* 1-5'/,
  "the durable universe must recheck at 17:10 and 21:10 Asia\/Taipei");
assert.match(dateReconcile, /x-twss-sync-token[\s\S]*vault\.decrypted_secrets/,
  "the evening reconciliation must keep using the Vault-protected sync token");
assert.match(dateReconcile, /create or replace function public\.twss_admin_schedule_status\(\)/,
  "the administrator must be able to distinguish a missing cron from an in-progress sync");
assert.match(dateReconcile, /where j\.jobname = 'twss-universe-evening-reconcile'/,
  "scheduler readiness must inspect the active evening reconciliation job");
assert.match(dateReconcile, /revoke all on function public\.twss_admin_schedule_status\(\)[\s\S]*from public, anon, authenticated/,
  "scheduler diagnostics must remain restricted to authenticated administrators");

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
assert.match(diagnosticPrivacy,
  /revoke all on function public\.twss_public_data_health\(\)[\s\S]*from public, anon, authenticated[\s\S]*to service_role/,
  "data-health diagnostics must be callable only by the service role");
assert.match(diagnosticPrivacy,
  /revoke all on function public\.twss_public_missing_data\(integer\)[\s\S]*from public, anon, authenticated[\s\S]*to service_role/,
  "missing-data diagnostics must be callable only by the service role");
assert.match(diagnosticPrivacy, /revoke all on table public\.stock_sync_state from public, anon, authenticated/,
  "raw synchronization state must not be readable through the public Data API");
assert.match(diagnosticPrivacy, /drop policy if exists stock_sync_state_public_read/,
  "the permissive synchronization-state RLS policy must be removed");
assert.match(diagnosticPrivacy, /revoke all on table public\.stock_analysis_cache from public, anon, authenticated/);
assert.match(diagnosticPrivacy, /grant select \([\s\S]*result,[\s\S]*updated_at[\s\S]*\) on table public\.stock_analysis_cache to anon, authenticated/,
  "public analysis access must use a safe column allowlist");
assert.doesNotMatch(diagnosticPrivacy.match(/grant select \([\s\S]*?\) on table public\.stock_analysis_cache/)?.[0] || "",
  /last_error|attempt_count|next_retry_at|error_kind|needs_repair|repair_reasons/,
  "the public analysis allowlist must exclude internal retry and error diagnostics");
assert.match(restrictedContext, /select\s+a\.symbol,[\s\S]*a\.analysis\s+into target/,
  "the public context RPC must select only columns retained in the public allowlist");
assert.doesNotMatch(restrictedContext, /select \* into target/,
  "the public context RPC must not regain access to the whole analysis-cache row");
assert.match(adminDashboard, /create table if not exists public\.app_admins[\s\S]*enable row level security/,
  "administrator membership must be stored in an RLS-protected table");
assert.match(adminDashboard, /create policy app_admins_read_self[\s\S]*user_id = \(select auth\.uid\(\)\)/,
  "signed-in users may inspect only their own administrator membership");
assert.match(adminDashboard, /revoke all on table public\.app_admins from public, anon, authenticated[\s\S]*grant select on table public\.app_admins to authenticated/);
assert.match(adminDashboard, /create or replace function public\.twss_is_admin\(\)[\s\S]*a\.active/,
  "administrator discovery must require an active server-managed membership");
const adminLogFunction = adminDashboard.match(
  /create or replace function public\.twss_admin_operations_log[\s\S]*?comment on function public\.twss_admin_operations_log/,
)?.[0] || "";
assert.match(adminLogFunction, /security definer[\s\S]*set search_path = ''/,
  "the privileged administrator aggregation must use a fixed empty search path");
assert.match(adminLogFunction, /auth\.uid\(\)[\s\S]*twss_is_admin\(\)[\s\S]*admin_required/,
  "the privileged administrator aggregation must reject non-admin callers before reading diagnostics");
assert.match(adminLogFunction, /greatest\(1, least\(coalesce\(p_limit, 60\), 100\)\)/,
  "administrator log limits must be bounded");
assert.match(adminLogFunction, /'latestDataDate'[\s\S]*where job_key = 'universe'/,
  "the administrator data date must come from the authoritative universe job");
assert.match(adminDashboard, /revoke all on function public\.twss_admin_operations_log\(integer\)[\s\S]*from public, anon, authenticated[\s\S]*to authenticated, service_role/,
  "anonymous callers must not execute the administrator log RPC");
assert.doesNotMatch(adminDashboard, /insert into public\.app_admins|@[A-Za-z0-9.-]+/,
  "source migrations must not hard-code an administrator account");

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
assert.match(finmindVault, /from vault\.decrypted_secrets/);
assert.match(finmindVault, /security definer[\s\S]*set search_path = ''/,
  "the Vault reader must use a fixed search path");
assert.match(finmindVault, /revoke all on function public\.twss_finmind_token\(\)[\s\S]*from public, anon, authenticated/);
assert.match(finmindVault, /grant execute on function public\.twss_finmind_token\(\)[\s\S]*to service_role/);
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
assert.match(marketHandler, /type === "ranking-backtest"/);
assert.doesNotMatch(marketHandler, /type === "(?:data-health|backend-status)"/,
  "administrative diagnostics must not have a public market-data route");
assert.doesNotMatch(marketHandler, /readDataHealth|readBackendStatus/);
assert.doesNotMatch(marketHandler, /payload \|\|= await buildPriceHistory/);
assert.match(workflow, /npm run export-data/);
assert.doesNotMatch(workflow, /npm run update-data/);
assert.match(exporter, /flag: "wx"/, "point-in-time files must be create-only");
assert.match(exporter, /error\?\.code !== "EEXIST"/, "only an existing immutable snapshot may be skipped");
assert.match(exporter, /skippedExistingSnapshot/, "the export must report an immutable-snapshot skip");
assert.match(exporter, /backtestReady/);
assert.match(exporter, /minimumGroupRatio: 0\.75/);
assert.match(backtest, /snapshotCoverage\?\.backtestReady === true/, "partial daily rankings must never enter the point-in-time backtest");
assert.match(backtest, /entry\.open/, "snapshot backtests must enter only at the next trading-day open");
assert.match(freeInsights, /opportunity_ranking_cycles/, "final ranking dates must be persisted separately from in-progress rows");
assert.match(backtestSchema, /opportunity_backtest_outcomes/, "matured ranking outcomes must persist in the backend");
assert.match(backtestSchema, /p\.trade_date > s\.signal_date/, "database backtests must not enter before the next trading day");
assert.match(backtestSchema, /matured_dates >= 25/, "validation metrics must remain hidden below the minimum mature-date count");
assert.match(backtestSchema, /security invoker/, "public validation and missing-data RPCs must retain caller RLS");
assert.match(hardening, /if v_scored < v_expected then[\s\S]*ranking_cycle_incomplete/,
  "ranking dates must remain building until scored rows meet the non-decreasing expected count");
assert.match(hardening, /greatest\(coalesce\(p_expected_count, 0\), coalesce\(v_existing_expected, 0\)\)/,
  "a retry must never lower an existing cycle's expected population");
assert.match(hardening, /create trigger preserve_final_score_history[\s\S]*before insert or update on public\.opportunity_score_history/,
  "finalized point-in-time score rows must be immutable during later same-day refreshes");
assert.match(hardening, /revoke all on function public\.twss_preserve_final_score_history\(\)\s+from public, anon, authenticated/,
  "the internal immutable-history trigger helper must not be directly callable by public roles");
assert.match(hardenedBacktest, /p\.trade_date > greatest\([\s\S]*s\.signal_date[\s\S]*Asia\/Taipei/,
  "database backtests must enter after the later of signal date and Taipei finalization date");
assert.match(hardenedBacktest, /from public\.opportunity_score_history membership/,
  "benchmark membership must come from the point-in-time score cross-section");
assert.doesNotMatch(hardenedBacktest, /stock_analysis_cache/,
  "historical benchmarks must not use today's surviving analysis cache membership");
assert.match(hardenedBacktest, /mfe_pct, mae_pct, 'unknown'/,
  "market regime must stay unknown rather than use future entry-to-exit returns");
assert.match(hardening, /delete from public\.opportunity_backtest_outcomes[\s\S]*where not exists[\s\S]*c\.status = 'final'/,
  "legacy orphan, incomplete, or invalid-entry outcomes must be removed before public rollups");
assert.match(hardening, /set benchmark_return_pct = null,[\s\S]*market_regime = 'unknown'/,
  "legacy survivorship-derived benchmark fields must be quarantined until recalculation");
assert.match(hardening, /a\.data_date = p_data_date[\s\S]*a\.analysis_version = p_analysis_version/,
  "peer percentiles must use the target's exact analysis date and version");
assert.match(hardening, /when nullif\(a\.stock ->> 'pe', ''\)::numeric > 0/,
  "loss-making and zero-PE rows must be excluded from valuation percentiles");
assert.match(hardening, /'premium_discount', pg_catalog\.abs/,
  "ETF premium/discount quality must compare absolute deviation from NAV");
assert.match(hardenedHealth, /coalesce\(min\(final_count\), 0\)/,
  "overall score-history readiness must equal the weakest independent group");
assert.match(hardenedHealth, /having count\(distinct c\.group_name\) = 3[\s\S]*select max\(score_date\) from common_dates/,
  "the common final date must exist as a finalized date in all three groups");
assert.match(hardenedHealth, /'perGroup', v_final_by_group/,
  "data health must disclose final-date counts separately for each market group");
assert.match(hardenedHealth, /h\.score_date = s\.cycle_date[\s\S]*h\.model_version = '16\.3'[\s\S]*h\.official/,
  "official counts must be scoped to the exact date and score version");
assert.doesNotMatch(hardenedHealth, /'lastError',/,
  "administrator health summaries must not return raw internal synchronization errors");
assert.match(hardenedHealth, /'lastErrorCode'/,
  "administrator health summaries should expose only stable error codes");
assert.match(hardenedMissing, /'datasets'.*jsonb_object_agg/s,
  "missing-data diagnostics must provide per-dataset aggregates");
assert.match(hardenedMissing, /jsonb_strip_nulls[\s\S]*'expectedPeriod'[\s\S]*'actualPeriod'/,
  "public evidence must be reduced to a safe diagnostic allowlist");
assert.match(hardenedMissing, /source_evidence ->> 'rowCount', r\.source_evidence ->> 'rows'/,
  "safe diagnostics must accept the actual source row-count field");
for (const dataset of [
  "monthly_revenue", "quarterly_revenue", "cash_conversion", "holdings", "deep_analysis",
  "etf_profile", "etf_premium_discount", "etf_tracking_error", "etf_fees", "etf_top10_concentration",
]) {
  assert.match(hardenedMissing, new RegExp(`'${dataset}'`),
    `${dataset} gaps must remain independently diagnosable`);
}
assert.match(hardenedMissing, /v16\.3-source-coverage-audit/,
  "legacy generic repair flags must remain retryable during the v17 transition");
assert.match(hardenedMissing, /'deep_refresh'/,
  "last-good rows with a failed refresh need a separate API diagnostic");
assert.match(hardenedMissing, /financial,revenueStatus|revenueStatus/,
  "quarterly revenue diagnostics must distinguish non-comparable industries from missing source fields");
assert.match(hardenedMissing, /cashConversionBasis/,
  "cash conversion diagnostics must distinguish inapplicable ratios from missing cash-flow data");
assert.match(hardenedMissing, /cashConversionBasis}' = 'TTM-nonpositive-net-income'/,
  "only a non-positive TTM denominator may make cash conversion not applicable");
assert.doesNotMatch(hardenedMissing, /cashConversionBasis}' in \([\s\S]*insufficient-positive-income/,
  "insufficient positive-income history must remain partial instead of being hidden as not applicable");
assert.match(hardenedMissing, /'official-not-provided' then 'official_not_provided'/,
  "known free-source ETF omissions must be explicit instead of becoming misleading zero scores");
assert.match(hardenedMissing, /where c\.dataset_key = s\.dataset_key and c\.retryable/,
  "retryable counts must remain independent from the user-facing failure classification");
assert.doesNotMatch(hardenedMissing, /source_status in \([^)]*upstream[^)]*\) or error_kind is not null/,
  "a row-level refresh error must not relabel every otherwise valid dataset as an API failure");
assert.match(hardenedMissing, /'insufficient-history'/,
  "per-dataset history depth must be distinguished from missing and upstream-error states");
assert.doesNotMatch(hardenedMissing, /'repairReasons'/,
  "public missing-data evidence must not expose internal repair implementation details");
assert.match(config, /verify_jwt = false/);
assert.match(config, /entrypoint = "\.\/functions\/twss-sync-batch\/index\.ts"/);
assert.match(trim, /analysis - 'priceHistory'/);
assert.doesNotMatch(config, /gemini|ai[_-]?research|twss-ai/i,
  "removed paid research Edge Function must not remain configured");
assert.doesNotMatch(marketHandler, /gemini|ai[_-]?research|readAiResearch/i,
  "market routes must not expose removed paid research features");
assert.doesNotMatch(sync, /gemini|ai[_-]?research/i,
  "the free public-data synchronization worker must be independent of paid research services");

console.log("Backend pipeline tests passed: bounded cursors, shared quota, Vault auth, RLS, and read-only grants");
