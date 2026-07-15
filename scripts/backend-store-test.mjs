import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const calls = [];
const groupRows = {
  listed: [{
    symbol: "2330", group_name: "listed", data_date: "2026-07-14", score: 82,
    confidence: 91, official: true, tier: "正式候選", stock: { symbol: "2330", name: "台積電" },
    analysis: { price: { lastDate: "2026-07-13" } }, result: {
      score: 82, confidence: 91,
      categories: [{ key: "growth", label: "成長", score: 84, weight: 30, coverage: 90, items: [{ key: "rev", score: 80 }] }],
    },
    updated_at: "2026-07-14T04:00:00Z",
  }],
  otc: [{
    symbol: "6488", group_name: "otc", data_date: "2026-07-13", score: 77,
    confidence: 88, official: true, tier: "正式候選", stock: { symbol: "6488", name: "環球晶" },
    analysis: { price: { lastDate: "2026-07-13" } }, result: { score: 77, confidence: 88 },
    updated_at: "2026-07-14T04:05:00Z",
  }],
  etf: [],
};
const finalCycles = {
  listed: [
    { group_name: "listed", score_date: "2026-07-14", model_version: "16.3", status: "final", official_count: 2 },
    { group_name: "listed", score_date: "2026-07-13", model_version: "16.3", status: "final", official_count: 2 },
  ],
  otc: [
    { group_name: "otc", score_date: "2026-07-14", model_version: "16.3", status: "final", official_count: 1 },
  ],
  etf: [],
};
const scoreRows = {
  listed: {
    "2026-07-14": [
      { symbol: "2330", score_date: "2026-07-14", score: 82, confidence: 91, official: true },
      { symbol: "2317", score_date: "2026-07-14", score: 80, confidence: 90, official: true },
    ],
    "2026-07-13": [
      { symbol: "2317", score_date: "2026-07-13", score: 81, confidence: 90, official: true },
      { symbol: "2330", score_date: "2026-07-13", score: 79, confidence: 91, official: true },
    ],
  },
  otc: {
    "2026-07-14": [
      { symbol: "6488", score_date: "2026-07-14", score: 77, confidence: 88, official: true },
    ],
  },
  etf: {},
};

globalThis.fetch = async (input, options = {}) => {
  const url = new URL(String(input));
  calls.push({ url, options });
  assert.equal(options.headers.apikey.startsWith("sb_publishable_"), true);
  assert.equal("authorization" in options.headers, false, "public reads must not expose a service secret");

  if (url.pathname.endsWith("/stock_sync_state")) {
    return Response.json([
      {
        job_key: "deep_otc", status: "success", processed_count: 12,
        last_error: "FinMind https://api.example.test/private?token=secret HTTP 429 quota exceeded",
        details: {
          remaining: 300,
          benchmarks: { TAIEX: [{ date: "2026-07-13", close: 24000 }] },
          failures: [{ symbol: "6488", error: "GET https://api.example.test/private HTTP 429 token=secret" }],
          rankingFinalization: {
            status: "error",
            error: "POST https://database.example.test/rpc returned HTTP 502 secret=hidden",
          },
        },
      },
      {
        job_key: "universe", status: "success", cycle_date: "2026-07-14",
        details: { groupDates: { listed: "2026-07-14", otc: "2026-07-14", etf: "2026-07-14" } },
      },
    ]);
  }
  if (url.pathname.endsWith("/stock_price_history")) {
    const rows = Array.from({ length: 65 }, (_, index) => ({
      trade_date: new Date(Date.UTC(2026, 0, index + 1)).toISOString().slice(0, 10),
      open: 100 + index, high: 102 + index, low: 99 + index, close: 101 + index,
      volume: 500_000 + index, trade_value: 50_000_000, transactions: 2_000,
    })).reverse();
    return Response.json(rows);
  }
  if (url.pathname.endsWith("/opportunity_ranking_cycles")) {
    const group = ["listed", "otc", "etf"].find((item) => url.searchParams.get("group_name") === `eq.${item}`);
    return Response.json(finalCycles[group]);
  }
  if (url.pathname.endsWith("/opportunity_score_history")) {
    const group = ["listed", "otc", "etf"].find((item) => url.searchParams.get("group_name") === `eq.${item}`);
    const date = url.searchParams.get("score_date")?.replace(/^eq\./, "");
    return Response.json(scoreRows[group]?.[date] || []);
  }
  if (url.pathname.endsWith("/rpc/twss_get_stock_context")) {
    return Response.json({
      available: true,
      symbol: "2330",
      peer: { scope: "industry", peerCount: 12, metrics: [] },
      trend: { status: "ready", finalDateCount: 2, series: [] },
    });
  }
  if (url.pathname.endsWith("/rpc/twss_public_data_health")) {
    return Response.json({ version: "17.0", overallStatus: "healthy", dataDate: "2026-07-14", scoreHistory: { status: "ready" } });
  }
  if (url.pathname.endsWith("/rpc/twss_public_missing_data")) {
    return Response.json({
      datasets: { revenue: { total: 2, retryable: 2, classifications: { scheduled_repair: 2 } } },
      summary: [{ dataset: "revenue", classification: "scheduled_repair", count: 2 }],
      examples: [],
    });
  }
  if (url.pathname.endsWith("/rpc/twss_public_ranking_backtest")) {
    return Response.json({ version: "17.0", status: "insufficient_history", snapshotCount: 1, minimumSnapshots: 25, byGroup: {} });
  }
  if (url.pathname.endsWith("/stock_analysis_cache")) {
    if (url.searchParams.get("symbol") === "eq.2330") return Response.json(groupRows.listed);
    const group = ["listed", "otc", "etf"].find((item) => url.searchParams.get("group_name") === `eq.${item}`);
    if (options.method === "HEAD") {
      return new Response(null, { status: 200, headers: { "content-range": `0-0/${groupRows[group].length}` } });
    }
    return Response.json(groupRows[group]);
  }
  return Response.json({ error: "unmocked" }, { status: 404 });
};

const { readBackendAnalysis, readBackendHistory, readBackendRankings, readBackendStatus, readDataHealth, readRankingBacktest, backendStoreInternals } = await import("../src/backend-store.js");

const rankings = await readBackendRankings(100);
assert.equal(rankings.mode, "live");
assert.equal(rankings.version, "17.2");
assert.equal(rankings.scoreModelVersion, "16.3", "the frozen score model must remain identifiable separately from the API version");
assert.deepEqual(rankings.backend.counts, { listed: 1, otc: 1, etf: 0 });
assert.equal(rankings.groups.otc[0].stock.symbol, "6488");
assert.equal(rankings.groups.listed[0].result.score, 82);
assert.equal(rankings.groups.listed[0].result.categories[0].score, 84);
assert.equal(rankings.groups.otc[0].isStale, true, "last-good rows must remain visible across trading-date rollover");
assert.equal("items" in rankings.groups.listed[0].result.categories[0], false, "ranking payload must omit factor-level duplicates");
assert.equal("benchmarks" in rankings.backend.sync[0].details, false, "ranking payload must omit duplicated benchmark series");
assert.equal("last_error" in rankings.backend.sync[0], false, "public rankings must omit raw sync errors");
assert.equal(rankings.backend.sync[0].last_error_code, "rate_limited");
assert.deepEqual(rankings.backend.sync[0].details.failureSummary, {
  count: 1, byCode: { rate_limited: 1 },
});
assert.equal(rankings.backend.sync[0].details.rankingFinalization.errorCode, "upstream_unavailable");
assert.doesNotMatch(JSON.stringify(rankings.backend.sync), /https?:|secret|token=/i,
  "public sync state must not expose upstream URLs, credentials, or raw exception text");
assert.equal(rankings.generatedAt, "2026-07-14T04:05:00Z");
assert.equal(rankings.groups.listed[0].rank, 1);
assert.equal(rankings.groups.listed[0].previousRank, 2);
assert.equal(rankings.groups.listed[0].rankDelta, 1);
assert.equal(rankings.groups.listed[0].scoreDelta, 3);
assert.equal(rankings.groups.listed[0].trend.status, "ready");
assert.equal(rankings.groups.otc[0].trend.status, "date_mismatch", "a stale cache row must never inherit a newer finalized date's rank");
assert.equal(rankings.groups.otc[0].rank, null);
assert.equal(rankings.groups.otc[0].previousRank, null);
assert.equal(rankings.groups.otc[0].rankDelta, null);
assert.equal(rankings.groups.otc[0].scoreDelta, null);
assert.equal(backendStoreInternals.rankingTrend("6488", finalCycles.otc, scoreRows.otc["2026-07-14"]).status,
  "accumulating", "one final cycle must not produce a misleading rank change");

const history = await readBackendHistory("6488");
assert.equal(history.mode, "live");
assert.equal(history.count, 65);
assert.equal(history.history[0].date, "2026-01-01");
assert.equal(history.history.at(-1).close, 165);
await assert.rejects(() => readBackendHistory("6488' or true"), /格式不正確/);
const analysis = await readBackendAnalysis("2330");
assert.equal(analysis.stock.name, "台積電");
assert.equal(analysis.price.lastDate, "2026-07-13");
assert.equal(analysis.peer.peerCount, 12);
assert.equal(analysis.trend.status, "ready");
const dataHealth = await readDataHealth();
assert.equal(dataHealth.version, "17.2");
assert.equal(dataHealth.overallStatus, "healthy");
assert.equal(dataHealth.missingData.summary[0].classification, "scheduled_repair");
assert.equal(dataHealth.missingData.datasets.revenue.retryable, 2);
const rankingBacktest = await readRankingBacktest();
assert.equal(rankingBacktest.status, "insufficient_history");
assert.equal(rankingBacktest.version, "17.2", "public API patch version must override an older stored RPC label");
assert.equal(rankingBacktest.scoreModelVersion, "16.3");
const status = await readBackendStatus();
assert.equal(status.version, "17.2");
assert.equal(status.persistent, true);
assert.equal(status.jobs[0].processed_count, 12);
assert.equal("benchmarks" in status.jobs[0].details, false, "status payload must omit duplicated benchmark series");
assert.equal("last_error" in status.jobs[0], false);
assert.equal(status.jobs[0].last_error_code, "rate_limited");
assert.doesNotMatch(JSON.stringify(status.jobs), /https?:|secret|token=/i);
assert.ok(calls.every(({ url }) => url.hostname === "lfkdkdyaatdlizryiyon.supabase.co"));
assert.equal(calls.filter(({ url }) => url.pathname.endsWith("/stock_analysis_cache"))
  .some(({ url }) => url.searchParams.has("data_date")), false, "rankings must not discard last-good rows on date rollover");
assert.equal(calls.filter(({ url }) => url.pathname.endsWith("/stock_sync_state"))
  .every(({ url }) => url.searchParams.get("job_key") === "in.(universe,deep_listed,deep_otc,deep_etf)"), true,
"rankings and status must exclude per-symbol history lease rows");
assert.equal(calls.filter(({ url }) => url.pathname.endsWith("/opportunity_ranking_cycles"))
  .every(({ url }) => url.searchParams.get("status") === "eq.final" && url.searchParams.get("limit") === "2"), true,
"rank change calculations must read at most two explicitly final dates per group");
assert.equal(calls.filter(({ url }) => url.pathname.endsWith("/opportunity_score_history"))
  .every(({ url }) => url.searchParams.get("official") === "eq.true"), true,
"rank changes must use official score rows only");
const backendStoreSource = await readFile(new URL("../src/backend-store.js", import.meta.url), "utf8");
assert.doesNotMatch(backendStoreSource, /gemini|ai[_-]?research|readAiResearch/i,
  "paid research integration must not remain in the public backend store");
assert.equal(calls.some(({ url }) => /ai[_-]?stock|ai[_-]?research/i.test(url.pathname)), false,
  "backend tests must never request removed research tables");

console.log("Backend store tests passed: public-only reads, grouped rankings, sync state, and stored history");
