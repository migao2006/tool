import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { buildDeepDataFromStoredSources } from "../src/deep-data.js";
import {
  enrichmentQueueRows,
  finmindJobCost,
  hasUniverseDateRegression,
  normalizeLendingRows,
  officialHistoryRows,
} from "../supabase/functions/twss-sync-batch/db-first-utils.js";

const groupForStock = (stock) => stock.group;
const eligible = () => true;
const stocks = [
  {
    symbol: "2330",
    group: "listed",
    close: 1_000,
    open: 990,
    high: 1_010,
    low: 985,
    volume: 50_000,
    value: 50_000_000_000,
    foreign: 100,
    trust: 20,
    dealer: -5,
    inst: 115,
    marginBalance: 5_000,
    shortBalance: 100,
    revenue: 200_000,
    revPeriod: "2026-06",
    roe: 20,
    roePeriod: "2026 Q1",
  },
];
const dates = {
  price: { twse: "2026-07-16", tpex: "2026-07-16" },
  institutional: { twse: "2026-07-15", tpex: "2026-07-15" },
  margin: { twse: "2026-07-14", tpex: "2026-07-14" },
};
const official = officialHistoryRows(stocks, dates, "2026-07-16T10:00:00Z", groupForStock);
assert.equal(official.priceRows[0].trade_date, "2026-07-16");
assert.equal(official.institutionalRows[0].trade_date, "2026-07-15");
assert.equal(official.marginRows[0].trade_date, "2026-07-14");
assert.equal(official.sourceDatesBySymbol["2330"].margin, "2026-07-14");

const queue = enrichmentQueueRows({
  stocks,
  groupDates: { listed: "2026-07-16", otc: "2026-07-16", etf: "2026-07-16" },
  sourceDatesBySymbol: official.sourceDatesBySymbol,
  expectedRevenuePeriod: "2026-06",
  expectedFinancialPeriod: "2026 Q1",
  groupForStock,
  isEligible: eligible,
});
assert.deepEqual(queue.map((row) => row.dataset_key), ["lending", "institutional", "margin"]);
assert.equal(finmindJobCost("financial"), 3);
assert.equal(finmindJobCost("lending"), 1);
assert.equal(hasUniverseDateRegression(
  { listed: "2026-07-15", otc: "2026-07-15", etf: "2026-07-15" },
  "2026-07-16",
), true);
assert.equal(hasUniverseDateRegression(
  { listed: "2026-07-16", otc: "2026-07-16", etf: "2026-07-16" },
  "2026-07-16",
), false);

const lending = normalizeLendingRows("2330", [{
  date: "2026-07-15",
  transaction_volume: 10,
  balance: 20,
  ignored_price: 999,
}, {
  date: "2026-07-15",
  transaction_volume: 5,
}], "2026-07-16T10:00:00Z");
assert.equal(lending.length, 1);
assert.equal(lending[0].lending_value, 35);
assert.equal(lending[0].trade_date, "2026-07-15");

const storedDeep = buildDeepDataFromStoredSources("2330", "stock", "listed", {
  sourceData: {
    price_history: Array.from({ length: 25 }, (_, index) => ({
      trade_date: `2026-06-${String(index + 1).padStart(2, "0")}`,
      open: 100 + index,
      high: 102 + index,
      low: 99 + index,
      close: 101 + index,
      volume: 1_000 + index,
    })),
    financials: [{
      report_period: "2026 Q1",
      report_date: "2026-03-31",
      revenue: 1_000,
      net_income: 100,
      eps: 2,
    }],
  },
  currentQuote: { priceDate: "2026-06-25", close: 125, high: 126, low: 124, volume: 1_100 },
});
assert.equal(storedDeep.financial.sourceCoverage.incomeRows, 1);
assert.equal(storedDeep.financial.sourceCoverage.balanceRows, 0);
assert.equal(storedDeep.financial.sourceCoverage.cashflowRows, 0);
assert.equal(storedDeep.sourceDiagnostics.balance.status, "empty-no-history");
assert.equal(storedDeep.sourceDiagnostics.cashflow.status, "empty-no-history");

const workerSource = await readFile(
  new URL("../supabase/functions/twss-sync-batch/index.ts", import.meta.url),
  "utf8",
);
const workerLeaseMigration = await readFile(
  new URL("../supabase/migrations/20260716142004_harden_enrichment_worker_leases.sql", import.meta.url),
  "utf8",
);
const baseStart = workerSource.indexOf("async function syncDeepDatabaseUnlocked");
const baseEnd = workerSource.indexOf("async function syncDeep(", baseStart);
const basePath = workerSource.slice(baseStart, baseEnd);
assert.ok(baseStart >= 0 && baseEnd > baseStart, "database-first base worker must exist");
assert.ok(!basePath.includes("reserveFinmindBatch("), "base worker must not reserve FinMind calls");
assert.ok(!basePath.includes("buildDeepData("), "base worker must not call provider-backed deep analysis");
assert.match(workerSource.slice(baseEnd, baseEnd + 250), /syncDeepDatabaseUnlocked/);
assert.match(workerSource, /hasUniverseDateRegression\(groupDates, storedAligned\.dataDate\)/);
assert.match(basePath, /selectedCandidateRows\(group, date, limit, \{ ignoreBackoff: true \}\)/,
  "stored-data base analysis must ignore obsolete provider retry backoff");

const claimLeaseSql = workerLeaseMigration.match(
  /create or replace function public\.twss_claim_enrichment_batch[\s\S]*?create or replace function public\.twss_renew_enrichment_leases/,
)?.[0] || "";
const failLeaseSql = workerLeaseMigration.match(
  /create or replace function public\.twss_fail_enrichment[\s\S]*?create or replace function public\.twss_release_enrichment/,
)?.[0] || "";
const releaseLeaseSql = workerLeaseMigration.match(
  /create or replace function public\.twss_release_enrichment[\s\S]*?revoke all on function/,
)?.[0] || "";
assert.match(workerLeaseMigration, /claim_count integer not null default 0/);
assert.match(workerLeaseMigration, /lease_timeout_count integer not null default 0/);
assert.match(workerLeaseMigration, /lease_renewed_at timestamptz/);
const legacyAttemptConversion = workerLeaseMigration.match(
  /update public\.stock_enrichment_queue q[\s\S]*?where q\.error_kind is null[\s\S]*?q\.last_error is null[\s\S]*?;/,
)?.[0] || "";
assert.ok(
  workerLeaseMigration.indexOf(legacyAttemptConversion) < workerLeaseMigration.indexOf("create or replace function public.twss_claim_enrichment_batch"),
  "legacy claim counters must be converted before the RPC changes attempt semantics",
);
assert.match(legacyAttemptConversion, /claim_count = greatest\(q\.claim_count, q\.attempt_count\)/,
  "legacy no-error attempts must become observable claims");
assert.match(legacyAttemptConversion, /q\.status = 'running'[\s\S]*greatest\(q\.lease_timeout_count, greatest\(q\.attempt_count - 1, 0\)\)/,
  "repeated no-error running claims must become lease timeout history");
assert.match(legacyAttemptConversion, /coalesce\(q\.lease_renewed_at, q\.last_attempt_at, q\.updated_at, q\.created_at\)/,
  "an active legacy lease needs a heartbeat baseline during rollout");
assert.match(legacyAttemptConversion, /attempt_count = 0/,
  "no-error rows must start the new provider failure counter at zero");
assert.match(claimLeaseSql, /least\(coalesce\(p_limit, 15\), 15\)/,
  "database claims must cap each pool at fifteen jobs");
assert.match(claimLeaseSql, /for update of q skip locked/,
  "parallel token pools must never block each other's queue claims");
assert.match(claimLeaseSql, /claim_count = q\.claim_count \+ 1/);
assert.match(claimLeaseSql, /lease_timeout_count = q\.lease_timeout_count \+ case when c\.lease_expired then 1 else 0 end/);
assert.doesNotMatch(claimLeaseSql, /attempt_count = q\.attempt_count \+ 1/,
  "leasing or reclaiming work must not consume a provider failure attempt");
assert.match(failLeaseSql, /attempt_count = q\.attempt_count \+ 1/,
  "only an actual job failure should consume an attempt");
assert.doesNotMatch(releaseLeaseSql, /attempt_count\s*=/,
  "safely releasing unstarted work must not alter failure attempts");
assert.match(workerLeaseMigration, /twss_renew_enrichment_leases[\s\S]*q\.lease_until >= pg_catalog\.clock_timestamp\(\)/,
  "heartbeats must never revive an already expired lease");
assert.match(workerLeaseMigration, /revoke all on function public\.twss_renew_enrichment_leases[\s\S]*from public, anon, authenticated/);
assert.match(workerLeaseMigration, /grant execute on function public\.twss_renew_enrichment_leases[\s\S]*to service_role/);
assert.match(workerSource, /const ENRICHMENT_BATCH_LIMIT = 15/);
assert.match(workerSource, /const ENRICHMENT_CONCURRENCY = 3/);
assert.match(workerSource, /const ENRICHMENT_HEARTBEAT_MS = 60_000/);
assert.match(workerSource, /const ENRICHMENT_WORKER_DEADLINE_MS = 300_000/);
assert.match(workerSource, /rpc\/twss_renew_enrichment_leases/);
assert.match(workerSource, /Promise\.all\([\s\S]*Math\.min\(ENRICHMENT_CONCURRENCY, allowed\.length\)/,
  "each token pool should process no more than three jobs concurrently");
assert.match(workerSource, /const stopped = allowed\.filter\(\(job\) => !startedIds\.has/,
  "deadline or provider pauses must release every unstarted job");

console.log("DB-first sync helpers passed.");
