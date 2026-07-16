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

const marketSnapshotRows = ["6488", ...Array.from({ length: 1004 }, (_, index) => String(7000 + index))]
  .map((symbol) => ({
    symbol, trade_date: "2026-07-14", market: "上櫃", industry: "半導體業",
    instrument_type: "股票", open: 100, high: 103, low: 99, close: 102,
    change_pct: 2, volume: 5000, trade_value: 510000000, transactions: 3000,
    raw_data: { name: `測試公司 ${symbol}` }, source_dates: { price: "2026-07-14" },
  }));

globalThis.fetch = async (input, options = {}) => {
  const url = new URL(String(input));
  calls.push({ url, options });
  assert.equal(options.headers.apikey.startsWith("sb_publishable_"), true);
  assert.equal("authorization" in options.headers, false, "public reads must not expose a service secret");

  if (url.pathname.endsWith("/stock_price_history")) {
    const rows = Array.from({ length: 65 }, (_, index) => ({
      trade_date: new Date(Date.UTC(2026, 0, index + 1)).toISOString().slice(0, 10),
      open: 100 + index, high: 102 + index, low: 99 + index, close: 101 + index,
      volume: 500_000 + index, trade_value: 50_000_000, transactions: 2_000,
    })).reverse();
    return Response.json(rows);
  }
  if (url.pathname.endsWith("/stock_snapshots")) {
    if (url.searchParams.get("select") === "trade_date") {
      return Response.json([{ trade_date: "2026-07-14" }]);
    }
    const after = url.searchParams.get("symbol")?.replace(/^gt\./, "") || "";
    const limit = Number(url.searchParams.get("limit")) || 1000;
    return Response.json(marketSnapshotRows.filter((row) => row.symbol > after).slice(0, limit));
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

const { readBackendAnalysis, readBackendHistory, readBackendMarketStocks, readBackendRankings, readRankingBacktest, backendStoreInternals } = await import("../src/backend-store.js");

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
assert.equal("sync" in rankings.backend, false, "public rankings must not include administrative synchronization state");
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
const otcFallback = await readBackendMarketStocks("otc");
assert.equal(otcFallback.date, "2026-07-14");
assert.equal(otcFallback.stocks[0].symbol, "6488");
assert.equal(otcFallback.stocks.length, 1005, "market fallback must keyset-page beyond PostgREST's 1,000-row cap");
assert.equal(otcFallback.fetchedCount, 1005);
assert.equal(otcFallback.complete, true);
assert.equal(otcFallback.stocks[0].backendFallback, true);
const rankingBacktest = await readRankingBacktest();
assert.equal(rankingBacktest.status, "insufficient_history");
assert.equal(rankingBacktest.version, "17.2", "public API patch version must override an older stored RPC label");
assert.equal(rankingBacktest.scoreModelVersion, "16.3");
assert.ok(calls.every(({ url }) => url.hostname === "lfkdkdyaatdlizryiyon.supabase.co"));
assert.equal(calls.filter(({ url }) => url.pathname.endsWith("/stock_analysis_cache"))
  .some(({ url }) => url.searchParams.has("data_date")), false, "rankings must not discard last-good rows on date rollover");
assert.equal(calls.some(({ url }) => url.pathname.endsWith("/stock_sync_state")), false,
  "public reads must never request administrative synchronization state");
assert.equal(calls.some(({ url }) => /twss_public_(?:data_health|missing_data)/.test(url.pathname)), false,
  "public reads must never call administrator-only diagnostic RPCs");
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
const marketPageCalls = calls.filter(({ url }) =>
  url.pathname.endsWith("/stock_snapshots") && url.searchParams.get("select") !== "trade_date");
assert.equal(marketPageCalls.length, 3, "keyset pagination must continue through the empty EOF page");
assert.equal(marketPageCalls[0].url.searchParams.has("symbol"), false);
assert.match(marketPageCalls[1].url.searchParams.get("symbol"), /^gt\./);
assert.equal(marketPageCalls.every(({ url }) => !url.searchParams.has("offset")), true);

console.log("Backend store tests passed: public-only reads, grouped rankings, stored history, and complete keyset market paging");
