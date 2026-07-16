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

const detailSignalRow = {
  ...rankingRows[0],
  symbol: "2330",
  signal_date: "2026-07-16",
  official: false,
  gate_passed: false,
  gate_results: {
    data_complete: true,
    tradeable_liquid: true,
    market_allowed: true,
    trend_structure: false,
    relative_strength: false,
    evidence_support: true,
    positive_expectancy: true,
    probabilityBasis: "deterministic-quant-rule-v20-bootstrap",
  },
  feature_scores: {
    technicalTrend: 64,
    volumePrice: 61,
    institutional: 58,
    market: 18,
    industry: 55,
    news: 50,
    fundamentalSafety: 70,
    liquidity: 82,
  },
  return_p10: -4.2,
  return_p50: 1.1,
  return_p90: 6.3,
  mfe: 7.2,
  mae: -5.1,
  target_first_probability: 56,
  entry_low: 100,
  entry_high: 102,
  stop_loss: 95,
  take_profit_1: 107,
  take_profit_2: 114,
  risk_reward_ratio: 2,
  recommended_holding_days: 5,
  reasons: ["短期策略：趨勢拉回"],
  risks: ["趨勢結構未通過"],
};

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
  if (url.pathname.endsWith("/v20_model_signals")) {
    const symbol = String(url.searchParams.get("symbol") || "").replace("eq.", "");
    return Response.json(symbol === "2330" ? [detailSignalRow] : []);
  }
  if (url.pathname.endsWith("/rpc/twss_v20_public_stock_signals")) {
    const symbol = url.searchParams.get("p_symbol");
    return Response.json(symbol === "2332" ? [{ ...detailSignalRow, symbol: "2332" }] : []);
  }
  if (url.pathname.endsWith("/v20_market_context")) return Response.json([]);
  throw new Error(`unexpected Supabase path: ${url.pathname}`);
};

const backend = await import(`../src/v20-backend.js?test=${Date.now()}`);
const rankingsRoute = (await import(`../api/v20/rankings.js?test=${Date.now()}`)).default;
const marketRoute = (await import(`../api/v20/market.js?test=${Date.now()}`)).default;
const stocksRoute = (await import(`../api/v20/stocks.js?test=${Date.now()}`)).default;
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
  const normalizedRelated = backend.v20BackendInternals.normalizeLegacyRelatedStock({
    symbol: "2618",
    aiScore: { value: 83, confidence: 79 },
    analysisDataDate: "2026-07-16T00:00:00Z",
  });
  assert.equal(normalizedRelated.aiScore, 83);
  assert.equal(normalizedRelated.opportunityScore, 83);
  assert.equal(normalizedRelated.confidence, 79);
  assert.equal(normalizedRelated.dataDate, "2026-07-16");
  assert.equal(normalized.recommendedAction, "資料不足");

  const globalContext = Object.fromEntries([
    "nasdaq", "sp500", "sox", "tsmAdr", "nvidia", "vix", "us10y", "usdTwd",
  ].map((key, index) => [key, { value: 100 + index, dataDate: "2026-07-15" }]));
  const resolvedMarket = backend.v20BackendInternals.normalizeMarket({
    global_context: globalContext,
    degraded_sources: ["international_context", "global_market_context", "taiex_official_index"],
  });
  assert.deepEqual(
    backend.v20BackendInternals.pruneResolvedDegradedSources(resolvedMarket.degradedSources, resolvedMarket),
    ["taiex_official_index"],
    "usable persisted international indicators must clear stale umbrella degraded flags",
  );

  const bootstrap = backend.v20BackendInternals.normalizeRanking(detailSignalRow);
  assert.equal(bootstrap.predictionState.status, "not_calibrated");
  assert.equal(bootstrap.predictionState.publicForecast, false);
  assert.equal(bootstrap.forecasts["5"].upProbability, null,
    "non-Walk-forward probability must never be exposed by the public contract");
  assert.equal(bootstrap.forecasts["5"].expectedNetReturn, null);
  assert.deepEqual(bootstrap.forecasts["5"].returnRange, { p10: null, p50: null, p90: null });
  assert.equal(bootstrap.forecasts["5"].averageMfe, null);
  assert.equal(bootstrap.forecasts["5"].averageMae, null);
  assert.equal(bootstrap.forecasts["5"].targetFirstProbability, null);
  assert.equal(bootstrap.expectedValue, null);
  assert.equal(bootstrap.opportunityScore, detailSignalRow.opportunity_score,
    "hiding uncalibrated forecasts must preserve the deterministic opportunity score");
  assert.equal(bootstrap.tradePlan.stopLoss, 95);
  assert.equal(bootstrap.gateReasons.find((item) => item.key === "trend_structure")?.status, "fail");
  assert.equal(bootstrap.gateReasons.find((item) => item.key === "confidence_threshold")?.status, "pass");
  assert.equal(bootstrap.scoreExplanation.find((item) => item.key === "market")?.weight, 15);
  assert.equal(bootstrap.marketImpact.opportunityDeltaFromNeutral, -4.8);

  const calibrated = backend.v20BackendInternals.normalizeRanking({
    ...detailSignalRow,
    prediction_basis: "walk-forward-calibration",
    up_probability: 63,
    expected_return_net: 2.1,
    expected_value: 2.1,
    return_p10: -3,
    return_p50: 2,
    return_p90: 7,
    mfe: 8,
    mae: -4,
    target_first_probability: 59,
  });
  assert.equal(calibrated.predictionState.status, "calibrated");
  assert.equal(calibrated.forecasts["5"].upProbability, 63);
  assert.equal(calibrated.forecasts["5"].expectedNetReturn, 2.1);
  assert.equal(calibrated.forecasts["5"].averageMfe, 8);
  assert.equal(calibrated.expectedValue, 2.1);

  calls.length = 0;
  const privateSignals = await backend.v20BackendInternals.loadSignals("2330", "2026-07-16");
  assert.equal(privateSignals.length, 1,
    "server-side detail reads must include a non-official signal hidden by public table RLS");
  const privateRead = calls.find((call) => call.url.pathname.endsWith("/v20_model_signals"));
  assert.equal(privateRead.init.headers.apikey, "test-service-role-key");
  assert.equal(privateRead.init.headers.authorization, "Bearer test-service-role-key");
  assert.equal(privateRead.url.searchParams.get("signal_date"), "eq.2026-07-16");

  calls.length = 0;
  const fallbackSignals = await backend.v20BackendInternals.loadSignals("2332", "2026-07-16");
  assert.equal(fallbackSignals.length, 1, "empty service reads must fall back to the bounded public symbol RPC");
  assert.ok(calls.some((call) => call.url.pathname.endsWith("/rpc/twss_v20_public_stock_signals")));
  const rpcRead = calls.find((call) => call.url.pathname.endsWith("/rpc/twss_v20_public_stock_signals"));
  assert.notEqual(rpcRead.init.headers.apikey, "test-service-role-key",
    "the public fallback must not forward an elevated server credential");

  const missingModel = backend.v20BackendInternals.modelStateFor(
    "medium", [], { publishedDataDate: "2026-07-16" }, false,
  );
  assert.equal(missingModel.status, "not_generated");
  assert.match(missingModel.reason, /2026-07-16.*中期模型訊號/);
  assert.doesNotMatch(missingModel.reason, /完整度\s*0/,
    "a missing model row must not be misreported as zero data completeness");

  calls.length = 0;
  const stockResponse = await stocksRoute.fetch(new Request("https://app.test/api/v20/stocks?symbol=2330"));
  assert.equal(stockResponse.status, 200);
  const stockDetail = await stockResponse.json();
  assert.equal(stockDetail.short.length, 1,
    "the public stock endpoint must render non-official detail signals through the server credential");
  assert.equal(stockDetail.short[0].official, false);
  assert.equal(stockDetail.short[0].forecasts["5"].upProbability, null);
  assert.equal(stockDetail.modelStates.short.status, "ready");
  assert.equal(stockDetail.modelStates.medium.status, "not_generated");
  assert.match(stockDetail.modelStates.medium.reason, /中期模型訊號/);

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

  const [html, ui, smart, sw, manifest, generator, backendSource] = await Promise.all([
    readFile(new URL("../public/index.html", import.meta.url), "utf8"),
    readFile(new URL("../public/v20.js", import.meta.url), "utf8"),
    readFile(new URL("../public/smart.js", import.meta.url), "utf8"),
    readFile(new URL("../public/sw.js", import.meta.url), "utf8"),
    readFile(new URL("../public/manifest.webmanifest", import.meta.url), "utf8"),
    readFile(new URL("./generate-worker.mjs", import.meta.url), "utf8"),
    readFile(new URL("../src/v20-backend.js", import.meta.url), "utf8"),
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
  assert.match(ui, /未通過或待確認條件/);
  assert.match(ui, /預測尚未公開/);
  assert.match(ui, /modelState\?\.reason/,
    "empty model blocks must display the exact API diagnostic instead of a generic placeholder");
  assert.match(ui, /相對中性值/,
    "the detail UI must explain the stored market factor contribution without changing its formula");
  assert.match(ui, /item\.opportunityScore, item\.aiScore\?\.value, item\.score/,
    "related-stock scores must support the v19 aiScore object and numeric score fallback");
  assert.match(backendSource, /relatedStocks: arrays\(legacy\?\.relatedStocks\)\.map\(normalizeLegacyRelatedStock\)/,
    "the v20 API must normalize legacy related-stock scores before returning them");
  assert.doesNotMatch(ui, /localStorage\.setItem\([^\n]*(?:capital|cost|position)/i);
  const assetVersion = sw.match(/const CACHE='twss-v([^']+)'/)?.[1];
  assert.ok(assetVersion);
  const escapedAssetVersion = assetVersion.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  assert.match(sw, new RegExp(`v20\\.js\\?v=${escapedAssetVersion}`));
  assert.match(generator, /read\("public\/v20\.js"\)/);
  assert.match(generator, /path==="\/v20\.js"/);
  assert.equal(JSON.parse(manifest).start_url.includes(`v=${assetVersion}`), true);

  console.log("v20 API/UI contract: passed");
} finally {
  globalThis.fetch = originalFetch;
  if (originalInternalKey === undefined) delete process.env.TWSS_V20_INTERNAL_KEY;
  else process.env.TWSS_V20_INTERNAL_KEY = originalInternalKey;
  if (originalServiceKey === undefined) delete process.env.SUPABASE_SERVICE_ROLE_KEY;
  else process.env.SUPABASE_SERVICE_ROLE_KEY = originalServiceKey;
}
