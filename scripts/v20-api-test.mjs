import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const originalFetch = globalThis.fetch;
const originalInternalKey = process.env.TWSS_V20_INTERNAL_KEY;
const originalServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
process.env.SUPABASE_SERVICE_ROLE_KEY = "test-service-role-key";
const calls = [];

const rankingRows = [1, 2, 3].map((rank) => ({
  symbol: `233${rank - 1}`,
  name: `測試股票 ${rank}`,
  ranking_date: "2026-07-16",
  model_key: "short",
  horizon_days: 5,
  model_version: "20.0",
  group_name: "listed",
  market: "上市",
  industry: "半導體業",
  strategy_key: "momentum_breakout",
  rank_position: rank,
  opportunity_score: 90 - rank,
  risk_score: 20 + rank,
  confidence: 80,
  completeness: 90,
  expected_value: 2 - rank / 10,
  prediction_basis: rank === 1 ? "deterministic-quant-rule-v20-bootstrap" : "walk-forward-calibration",
  up_probability: rank === 1 ? 61 : null,
  expected_return_net: rank === 1 ? 2.5 : null,
  official: true,
  recommended_action: rank === 1 ? "可以布局" : "資料不足",
  generated_at: "2026-07-15T12:00:00Z",
}));

globalThis.fetch = async (input, init = {}) => {
  const url = new URL(String(input));
  calls.push({ url, init });
  if (url.hostname !== "lfkdkdyaatdlizryiyon.supabase.co") {
    throw new Error(`unexpected external request: ${url.hostname}`);
  }
  if (url.pathname.endsWith("/stock_sync_state")) {
    return Response.json([{ details: {
      publicationPhase: "enriching",
      publishedDataDate: "2026-07-16",
      baseCompletedAt: "2026-07-16T09:20:00Z",
      enrichmentCompletedAt: null,
      enrichmentPending: 523,
      sourceDates: { universe: "2026-07-16", listed: "2026-07-16", otc: "2026-07-16", etf: "2026-07-16" },
      dataCompleteness: 87.5,
    } }]);
  }
  if (url.pathname.endsWith("/v20_ranking_snapshots")) {
    if (url.searchParams.get("select") === "ranking_date") {
      return Response.json([{ ranking_date: "2026-07-16" }]);
    }
    const after = Number(String(url.searchParams.get("rank_position") || "gt.0").replace("gt.", ""));
    const offset = Number(url.searchParams.get("offset") || 0);
    const limit = Number(url.searchParams.get("limit") || 10);
    const ordered = String(url.searchParams.get("order") || "").startsWith("risk_score.asc")
      ? [...rankingRows].sort((left, right) => left.risk_score - right.risk_score)
      : rankingRows;
    return Response.json(ordered.filter((row) => row.rank_position > after).slice(offset, offset + limit));
  }
  if (url.pathname.endsWith("/v20_market_context")) return Response.json([]);
  throw new Error(`unexpected Supabase path: ${url.pathname}`);
};

const backend = await import(`../src/v20-backend.js?test=${Date.now()}`);
const rankingsRoute = (await import(`../api/v20/rankings.js?test=${Date.now()}`)).default;
const marketRoute = (await import(`../api/v20/market.js?test=${Date.now()}`)).default;
const shared = await import(`../api/v20/_shared.js?test=${Date.now()}`);

try {
  const parsed = backend.parseV20RankingQuery(new URLSearchParams({ model: "short" }));
  assert.equal(parsed.horizon, 5);
  assert.equal(parsed.sort, "expected_value_desc");
  assert.equal(parsed.afterRank, 0);
  assert.equal(parsed.offset, 0);

  const mixedCursor = backend.v20BackendInternals.encodeCursor(2, {
    ...parsed,
    groupDates: { listed: "2026-07-16", otc: "2026-07-15", etf: "2026-07-15" },
  }, 20);
  const mixedParsed = backend.parseV20RankingQuery(new URLSearchParams({ model: "short", cursor: mixedCursor }));
  assert.deepEqual(mixedParsed.groupDates, { listed: "2026-07-16", otc: "2026-07-15", etf: "2026-07-15" });

  const normalized = backend.v20BackendInternals.normalizeRanking(rankingRows[1]);
  assert.equal(normalized.forecasts["5"].upProbability, null);
  assert.equal(normalized.forecasts["5"].dataState, "insufficient_history");
  assert.equal(normalized.recommendedAction, "資料不足");

  backend.v20BackendInternals.clearCache();
  calls.length = 0;
  const firstResponse = await rankingsRoute.fetch(new Request(
    "https://app.test/api/v20/rankings?model=short&horizon=5&limit=2",
  ));
  assert.equal(firstResponse.status, 200);
  const first = await firstResponse.json();
  assert.equal(first.items.length, 2);
  assert.ok(first.nextCursor);
  for (const key of [
    "dataState", "dataDate", "sourceDates", "fetchedAt", "completeness", "degradedSources",
    "publicationPhase", "publishedDataDate", "baseCompletedAt", "enrichmentCompletedAt", "enrichmentPending", "dataCompleteness",
  ]) {
    assert.ok(Object.hasOwn(first, key), `missing response metadata: ${key}`);
  }
  assert.equal(first.dataDate, "2026-07-16");
  assert.equal(first.publicationPhase, "enriching");
  assert.equal(first.enrichmentPending, 523);
  assert.equal(first.dataCompleteness, 87.5);
  const pageCall = calls.find((call) => call.url.searchParams.get("select") === "*");
  assert.equal(pageCall.url.searchParams.get("ranking_date"), "eq.2026-07-16",
    "all public ranking models must use the atomic publication pointer");
  assert.equal(pageCall.url.searchParams.get("order"), "rank_position.asc,symbol.asc");
  assert.equal(pageCall.url.searchParams.has("offset"), false);
  assert.equal(pageCall.init.headers?.Prefer, undefined, "page reads must not request exact counts");

  backend.v20BackendInternals.clearCache();
  calls.length = 0;
  const secondResponse = await rankingsRoute.fetch(new Request(
    `https://app.test/api/v20/rankings?model=short&horizon=5&limit=2&cursor=${encodeURIComponent(first.nextCursor)}`,
  ));
  assert.equal(secondResponse.status, 200);
  const second = await secondResponse.json();
  assert.deepEqual(second.items.map((row) => row.rank), [3]);
  const secondPageCall = calls.find((call) => call.url.searchParams.get("select") === "*");
  assert.equal(secondPageCall.url.searchParams.get("rank_position"), "gt.2");

  backend.v20BackendInternals.clearCache();
  calls.length = 0;
  const riskFirstResponse = await rankingsRoute.fetch(new Request(
    "https://app.test/api/v20/rankings?model=short&horizon=5&limit=2&sort=risk_asc",
  ));
  const riskFirst = await riskFirstResponse.json();
  assert.equal(riskFirstResponse.status, 200);
  assert.ok(riskFirst.nextCursor, "secondary sorts must remain pageable");
  backend.v20BackendInternals.clearCache();
  calls.length = 0;
  const riskSecondResponse = await rankingsRoute.fetch(new Request(
    `https://app.test/api/v20/rankings?model=short&horizon=5&limit=2&sort=risk_asc&cursor=${encodeURIComponent(riskFirst.nextCursor)}`,
  ));
  assert.equal(riskSecondResponse.status, 200);
  const riskSecond = await riskSecondResponse.json();
  assert.deepEqual(riskSecond.items.map((row) => row.rank), [3]);
  const riskPageCall = calls.find((call) => call.url.searchParams.get("select") === "*");
  assert.equal(riskPageCall.url.searchParams.get("offset"), "2");

  backend.v20BackendInternals.clearCache();
  calls.length = 0;
  const filteredResponse = await rankingsRoute.fetch(new Request(
    "https://app.test/api/v20/rankings?model=short&horizon=5&industry=半導體業&strategy=momentum_breakout&search=2330",
  ));
  assert.equal(filteredResponse.status, 200);
  const dateCalls = calls.filter((call) => call.url.searchParams.get("select") === "ranking_date");
  assert.equal(dateCalls.length, 0,
    "the atomic publication pointer removes per-filter latest-date discovery");
  const filteredPageCall = calls.find((call) => call.url.searchParams.get("select") === "*");
  assert.equal(filteredPageCall.url.searchParams.get("ranking_date"), "eq.2026-07-16");
  assert.equal(filteredPageCall.url.searchParams.get("industry"), "eq.半導體業");
  assert.equal(filteredPageCall.url.searchParams.get("strategy_key"), "eq.momentum_breakout");
  assert.ok(filteredPageCall.url.searchParams.has("or"));

  backend.v20BackendInternals.clearCache();
  calls.length = 0;
  const home = await backend.readV20Home();
  assert.equal(home.dataDate, "2026-07-16");
  assert.equal(home.publicationPhase, "enriching");
  assert.equal(home.dailyReport.dataDate, home.dataDate,
    "the base daily report must switch with the same atomic publication date");
  assert.equal(home.dailyReport.source, "v20-atomic-base-report");
  assert.equal(home.dailyReport.cachedFallback, false);
  assert.ok(home.dailyReport.report.oneLine);
  assert.equal(Object.hasOwn(home, "updateJobs"), false,
    "v20 public home must not expose legacy operational job status");

  process.env.TWSS_V20_INTERNAL_KEY = "server-only-test-key";
  backend.v20BackendInternals.clearCache();
  calls.length = 0;
  const market = await marketRoute.fetch(new Request("https://app.test/api/v20/market?refresh=global"));
  assert.equal(market.status, 200);
  assert.ok(calls.every((call) => call.url.hostname === "lfkdkdyaatdlizryiyon.supabase.co"),
    "unauthorized refresh must never call metered providers");

  const method = await shared.handleV20(new Request("https://app.test/api/v20/home", { method: "POST" }), async () => ({}));
  assert.equal(method.status, 405);

  const [html, ui, smart, sw, manifest, generator] = await Promise.all([
    readFile(new URL("../public/index.html", import.meta.url), "utf8"),
    readFile(new URL("../public/v20.js", import.meta.url), "utf8"),
    readFile(new URL("../public/smart.js", import.meta.url), "utf8"),
    readFile(new URL("../public/sw.js", import.meta.url), "utf8"),
    readFile(new URL("../public/manifest.webmanifest", import.meta.url), "utf8"),
    readFile(new URL("./generate-worker.mjs", import.meta.url), "utf8"),
  ]);
  for (const tab of ["home", "short", "medium", "watchlist", "analysis"]) {
    assert.match(html, new RegExp(`data-tab="${tab}"`));
  }
  assert.doesNotMatch(html, /data-tab="(?:prediction|journal|portfolio)"/i);
  assert.match(ui, /載入更多新聞與公告/);
  assert.match(ui, /twss-v19-daily-report-cache/);
  assert.match(ui, /\/data\/daily-report\.json/);
  assert.match(ui, /payload\.dailyReport/);
  assert.match(ui, /publicationPhase: 'cached'/,
    "the legacy static report must be labelled as a cached fallback");
  assert.match(ui, /dateKey\(atomicReport\.meta\.dataDate\) === dateKey\(payload\.dataDate\)/,
    "the UI must reject a report that does not match the published home date");
  assert.match(ui, /AI 每日報告/);
  assert.match(ui, /twssV19Benchmarks\?\.marketIndices/);
  assert.match(smart, /globalThis\.twssV19Benchmarks\s*=\s*value/);
  assert.match(ui, /不會儲存資金、成本或交易紀錄/);
  assert.match(ui, /item\.opportunityScore, item\.aiScore\?\.value, item\.score/,
    "related-stock scores must support the v19 aiScore object and numeric score fallback");
  assert.doesNotMatch(ui, /localStorage\.setItem\([^\n]*(?:capital|cost|position)/i);
  assert.match(sw, /twss-v20\.0\.5/);
  assert.match(sw, /v20\.js\?v=20\.0\.5/);
  assert.match(generator, /read\("public\/v20\.js"\)/);
  assert.match(generator, /path==="\/v20\.js"/);
  assert.equal(JSON.parse(manifest).start_url.includes("v=20.0.5"), true);

  console.log("v20 API/UI contract: passed");
} finally {
  globalThis.fetch = originalFetch;
  if (originalInternalKey === undefined) delete process.env.TWSS_V20_INTERNAL_KEY;
  else process.env.TWSS_V20_INTERNAL_KEY = originalInternalKey;
  if (originalServiceKey === undefined) delete process.env.SUPABASE_SERVICE_ROLE_KEY;
  else process.env.SUPABASE_SERVICE_ROLE_KEY = originalServiceKey;
}
