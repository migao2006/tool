import assert from "node:assert/strict";

const calls = [];
const groupRows = {
  listed: [{
    symbol: "2330", group_name: "listed", data_date: "2026-07-13", score: 82,
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

globalThis.fetch = async (input, options = {}) => {
  const url = new URL(String(input));
  calls.push({ url, options });
  assert.equal(options.headers.apikey.startsWith("sb_publishable_"), true);
  assert.equal("authorization" in options.headers, false, "public reads must not expose a service secret");

  if (url.pathname.endsWith("/stock_sync_state")) {
    return Response.json([
      {
        job_key: "deep_otc", status: "success", processed_count: 12,
        details: { remaining: 300, benchmarks: { TAIEX: [{ date: "2026-07-13", close: 24000 }] } },
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

const { readBackendAnalysis, readBackendHistory, readBackendRankings, readBackendStatus } = await import("../src/backend-store.js");

const rankings = await readBackendRankings(100);
assert.equal(rankings.mode, "live");
assert.equal(rankings.version, "16.3");
assert.deepEqual(rankings.backend.counts, { listed: 1, otc: 1, etf: 0 });
assert.equal(rankings.groups.otc[0].stock.symbol, "6488");
assert.equal(rankings.groups.listed[0].result.score, 82);
assert.equal(rankings.groups.listed[0].result.categories[0].score, 84);
assert.equal(rankings.groups.listed[0].isStale, true, "last-good rows must remain visible across trading-date rollover");
assert.equal("items" in rankings.groups.listed[0].result.categories[0], false, "ranking payload must omit factor-level duplicates");
assert.equal("benchmarks" in rankings.backend.sync[0].details, false, "ranking payload must omit duplicated benchmark series");
assert.equal(rankings.generatedAt, "2026-07-14T04:05:00Z");

const history = await readBackendHistory("6488");
assert.equal(history.mode, "live");
assert.equal(history.count, 65);
assert.equal(history.history[0].date, "2026-01-01");
assert.equal(history.history.at(-1).close, 165);
await assert.rejects(() => readBackendHistory("6488' or true"), /格式不正確/);
const analysis = await readBackendAnalysis("2330");
assert.equal(analysis.stock.name, "台積電");
assert.equal(analysis.price.lastDate, "2026-07-13");

const status = await readBackendStatus();
assert.equal(status.persistent, true);
assert.equal(status.jobs[0].processed_count, 12);
assert.equal("benchmarks" in status.jobs[0].details, false, "status payload must omit duplicated benchmark series");
assert.ok(calls.every(({ url }) => url.hostname === "lfkdkdyaatdlizryiyon.supabase.co"));
assert.equal(calls.filter(({ url }) => url.pathname.endsWith("/stock_analysis_cache"))
  .some(({ url }) => url.searchParams.has("data_date")), false, "rankings must not discard last-good rows on date rollover");

console.log("Backend store tests passed: public-only reads, grouped rankings, sync state, and stored history");
