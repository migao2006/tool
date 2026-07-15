import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const read = (path) => readFile(new URL(path, new URL("../", import.meta.url)), "utf8");
const checks = [];
const failures = [];

async function check(name, fn) {
  try {
    await fn();
    checks.push(name);
    console.log(`v19 OK  ${name}`);
  } catch (error) {
    failures.push({ name, error });
    console.error(`v19 ERR ${name}: ${error instanceof Error ? error.message : error}`);
  }
}

function jsonResponse(value, status = 200, headers = {}) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

const PAGE_UPDATED_AT = "2026-07-15T14:12:00.000Z";
const GENERATED_AT = "2026-07-15T14:10:00.000Z";
const FETCHED_AT = "2026-07-15T13:58:00.000Z";
const UPDATED_AT = "2026-07-15T14:05:00.000Z";
const GROUP_DATES = { listed: "2026-07-15", otc: "2026-07-15", etf: "2026-07-15" };

const rankingRows = [
  {
    symbol: "2330",
    score_date: "2026-07-15",
    model_version: "16.3",
    group_name: "listed",
    cycle_status: "final",
    rank_position: 1,
    previous_rank: 3,
    rank_delta: 2,
    score: 91.25,
    previous_score: 88,
    score_delta: 3.25,
    confidence: 72,
    official: true,
    tier: "A",
    name: "台積電",
    market: "上市",
    industry: "半導體業",
    instrument_type: "股票",
    risk_score: 8,
    ai_score: 91.25,
    ai_score_basis: "v16.3-fixed-weight-composite",
    trade_date: "2026-07-15",
    source_fetched_at: FETCHED_AT,
    source_updated_at: UPDATED_AT,
    generated_at: GENERATED_AT,
    stock_summary: {
      symbol: "2330",
      name: "台積電",
      market: "上市",
      industry: "半導體業",
      instrumentType: "股票",
      priceDate: "2026-07-15",
    },
    result_summary: {
      symbol: "2330",
      name: "台積電",
      group: "listed",
      score: 91.25,
      confidence: 72,
      official: true,
      reasons: ["固定公式分數"],
      risk: { deduction: 8 },
      categories: [],
    },
    score_dimensions: {
      overall: { value: 91.25, basis: "v16.3-fixed-weight-composite" },
      confidence: { value: 72, basis: "v16.3-source-coverage-confidence" },
      risk: { value: 92, severity: 8, basis: "v16.3-risk-deduction-inverse" },
    },
  },
  {
    symbol: "2454",
    score_date: "2026-07-15",
    model_version: "16.3",
    group_name: "listed",
    cycle_status: "final",
    rank_position: 2,
    previous_rank: 2,
    rank_delta: 0,
    score: 83,
    previous_score: 84,
    score_delta: -1,
    confidence: 95,
    official: true,
    tier: "A",
    name: "聯發科",
    market: "上市",
    industry: "半導體業",
    instrument_type: "股票",
    risk_score: 22,
    ai_score: 83,
    ai_score_basis: "v16.3-fixed-weight-composite",
    trade_date: "2026-07-15",
    source_fetched_at: FETCHED_AT,
    source_updated_at: "2026-07-15T14:06:00.000Z",
    generated_at: GENERATED_AT,
    stock_summary: { symbol: "2454", name: "聯發科", market: "上市", industry: "半導體業" },
    result_summary: { symbol: "2454", name: "聯發科", group: "listed", score: 83, confidence: 95, official: true },
    score_dimensions: { overall: { value: 83, basis: "v16.3-fixed-weight-composite" } },
  },
  {
    symbol: "2603",
    score_date: "2026-07-15",
    model_version: "16.3",
    group_name: "listed",
    cycle_status: "final",
    rank_position: 3,
    previous_rank: 6,
    rank_delta: 3,
    score: 75,
    previous_score: 68,
    score_delta: 7,
    confidence: 60,
    official: true,
    tier: "B",
    name: "長榮",
    market: "上市",
    industry: "航運業",
    instrument_type: "股票",
    risk_score: 44,
    ai_score: 75,
    ai_score_basis: "v16.3-fixed-weight-composite",
    trade_date: "2026-07-15",
    source_fetched_at: FETCHED_AT,
    source_updated_at: "2026-07-15T14:04:00.000Z",
    generated_at: GENERATED_AT,
    stock_summary: { symbol: "2603", name: "長榮", market: "上市", industry: "航運業" },
    result_summary: { symbol: "2603", name: "長榮", group: "listed", score: 75, confidence: 60, official: true },
    score_dimensions: { overall: { value: 75, basis: "v16.3-fixed-weight-composite" } },
  },
  {
    symbol: "6488",
    score_date: "2026-07-15",
    model_version: "16.3",
    group_name: "otc",
    cycle_status: "final",
    rank_position: 1,
    previous_rank: 1,
    rank_delta: 0,
    score: 80,
    previous_score: 79,
    score_delta: 1,
    confidence: 70,
    official: true,
    tier: "A",
    name: "環球晶",
    market: "上櫃",
    industry: "半導體業",
    instrument_type: "股票",
    risk_score: 14,
    ai_score: 80,
    ai_score_basis: "v16.3-fixed-weight-composite",
    trade_date: "2026-07-15",
    source_fetched_at: FETCHED_AT,
    source_updated_at: UPDATED_AT,
    generated_at: GENERATED_AT,
    stock_summary: { symbol: "6488", name: "環球晶", market: "上櫃", industry: "半導體業" },
    result_summary: { symbol: "6488", name: "環球晶", group: "otc", score: 80, confidence: 70, official: true },
    score_dimensions: { overall: { value: 80, basis: "v16.3-fixed-weight-composite" } },
  },
  {
    symbol: "0050",
    score_date: "2026-07-15",
    model_version: "16.3",
    group_name: "etf",
    cycle_status: "final",
    rank_position: 1,
    previous_rank: 1,
    rank_delta: 0,
    score: 78,
    previous_score: 78,
    score_delta: 0,
    confidence: 99,
    official: true,
    tier: "A",
    name: "元大台灣50",
    market: "上市",
    industry: "ETF",
    instrument_type: "ETF",
    risk_score: 5,
    ai_score: 78,
    ai_score_basis: "v16.3-fixed-weight-composite",
    trade_date: "2026-07-15",
    source_fetched_at: FETCHED_AT,
    source_updated_at: UPDATED_AT,
    generated_at: GENERATED_AT,
    stock_summary: { symbol: "0050", name: "元大台灣50", market: "上市", industry: "ETF", instrumentType: "ETF" },
    result_summary: { symbol: "0050", name: "元大台灣50", group: "etf", score: 78, confidence: 99, official: true },
    score_dimensions: { overall: { value: 78, basis: "v16.3-fixed-weight-composite" } },
  },
];

const officialNews = [{
  id: "11111111-1111-4111-8111-111111111111",
  source: "twse-mops",
  market: "listed",
  symbols: ["2330"],
  company_name: "台積電",
  title: "營收成長",
  summary: "獲利創新高",
  category: "重大訊息",
  event_date: "2026-07-15",
  sentiment_label: "benefit",
  sentiment_score: 40,
  sentiment_basis: "official-disclosure-keyword-rule-v1",
  sentiment_terms: ["獲利", "成長"],
  source_url: "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
  published_at: "2026-07-15T01:15:30.000Z",
  fetched_at: FETCHED_AT,
  updated_at: FETCHED_AT,
}];

const calls = [];

function rpcArguments(url, options) {
  const args = Object.fromEntries(url.searchParams.entries());
  if (typeof options?.body === "string" && options.body) {
    try {
      Object.assign(args, JSON.parse(options.body));
    } catch {}
  }
  return args;
}

function sortRows(rows, sort) {
  const copy = [...rows];
  const number = (value, fallback) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  copy.sort((left, right) => {
    if (sort === "score_asc") return number(left.score, Infinity) - number(right.score, Infinity) || left.symbol.localeCompare(right.symbol);
    if (sort === "confidence_desc") return number(right.confidence, -Infinity) - number(left.confidence, -Infinity) || number(right.score, -Infinity) - number(left.score, -Infinity) || left.symbol.localeCompare(right.symbol);
    if (sort === "updated_desc") return String(right.source_updated_at || "").localeCompare(String(left.source_updated_at || "")) || left.symbol.localeCompare(right.symbol);
    if (sort === "change_desc") return number(right.score_delta, -Infinity) - number(left.score_delta, -Infinity) || left.symbol.localeCompare(right.symbol);
    if (sort === "risk_asc") return number(left.risk_score, Infinity) - number(right.risk_score, Infinity) || left.symbol.localeCompare(right.symbol);
    if (sort === "risk_desc") return number(right.risk_score, -Infinity) - number(left.risk_score, -Infinity) || left.symbol.localeCompare(right.symbol);
    return number(right.score, -Infinity) - number(left.score, -Infinity) || number(right.confidence, -Infinity) - number(left.confidence, -Infinity) || left.symbol.localeCompare(right.symbol);
  });
  return copy;
}

function rankingPage(args) {
  const group = args.p_group_name && args.p_group_name !== "null" ? String(args.p_group_name) : null;
  const industry = String(args.p_industry || "").trim().toLocaleLowerCase("zh-Hant");
  const search = String(args.p_search || "").trim().toLocaleLowerCase("zh-Hant");
  const sort = String(args.p_sort || "score_desc");
  const after = Math.max(0, Number(args.p_after_row) || 0);
  const limit = Math.max(1, Math.min(100, Number(args.p_limit) || 10));
  let rows = rankingRows.filter((row) => !group || row.group_name === group);
  if (industry) rows = rows.filter((row) => String(row.industry || "").toLocaleLowerCase("zh-Hant") === industry);
  if (search) rows = rows.filter((row) => [row.symbol, row.name, row.industry].join(" ").toLocaleLowerCase("zh-Hant").includes(search));
  rows = sortRows(rows, sort);
  const page = rows.slice(after, after + limit).map((row, index) => ({
    ...row,
    page_row: after + index + 1,
    total_count: rows.length,
  }));
  const selectedDates = Object.fromEntries(Object.entries(GROUP_DATES).filter(([key]) => !group || key === group));
  return {
    group_dates: selectedDates,
    group_statuses: Object.fromEntries(Object.keys(selectedDates).map((key) => [key, "final"])),
    items: page,
    total: rows.length,
    after_row: after,
    last_row: after + page.length,
    has_more: after + page.length < rows.length,
    snapshot_generated_at: GENERATED_AT,
    page_updated_at: PAGE_UPDATED_AT,
  };
}

async function mockFetch(input, options = {}) {
  const url = new URL(input instanceof Request ? input.url : String(input));
  const method = String(options.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
  calls.push({ url, method, options });
  if (url.origin !== "https://mock.supabase.local") {
    throw new Error(`Offline v19 test blocked a live request to ${url.origin}`);
  }

  const path = url.pathname.replace(/^\/rest\/v1\//, "");
  const args = rpcArguments(url, options);
  if (path.startsWith("rpc/twss_v19_current_rankings")) {
    return jsonResponse({ message: "all-row RPC forbidden by v19 contract" }, 599);
  }
  if (path.startsWith("rpc/twss_v19_rankings_page")) return jsonResponse(rankingPage(args));
  if (path.startsWith("rpc/twss_v19_public_job_status")) return jsonResponse([]);
  if (path.startsWith("v19_news_items")) return jsonResponse(officialNews);
  if (path.startsWith("stock_analysis_cache")) {
    return jsonResponse([{
      symbol: "2330",
      group_name: "listed",
      data_date: "2026-07-15",
      stock: { symbol: "2330", name: "台積電", priceDate: "2026-07-15", close: 1000 },
      analysis: { analysisVersion: "16.3-ultimate-data-audit", trend: { series: [] } },
      result: { score: 91.25, confidence: 72, official: true, categories: [], risk: { deduction: 8 } },
      analysis_version: "16.3-ultimate-data-audit",
      status: "ready",
      fetched_at: FETCHED_AT,
      updated_at: UPDATED_AT,
    }]);
  }
  if (path.startsWith("rpc/twss_get_stock_context")) return jsonResponse({ available: false, status: "unavailable" });
  if (method === "HEAD") return new Response(null, { status: 200, headers: { "content-range": "0-0/0" } });
  return jsonResponse([]);
}

process.env.SUPABASE_URL = "https://mock.supabase.local";
process.env.SUPABASE_PUBLISHABLE_KEY = "sb_publishable_offline_v19_test";
globalThis.fetch = mockFetch;

const backend = await import("../src/v19-backend.js");
const rankingsRoute = (await import("../api/v19/rankings.js")).default;
const homeRoute = (await import("../api/v19/home.js")).default;
const stocksRoute = (await import("../api/v19/stocks.js")).default;
const news = await import("../supabase/functions/_shared/v19-news.js");

const clearRuntime = () => {
  calls.length = 0;
  backend.v19BackendInternals?.clearCache?.();
};
const apiJson = async (response) => ({ response, body: await response.json() });
const rankingRpcCalls = () => calls.filter(({ url }) => url.pathname.endsWith("/rpc/twss_v19_rankings_page"));
const allRowRpcCalls = () => calls.filter(({ url }) => url.pathname.endsWith("/rpc/twss_v19_current_rankings"));

await check("API supports GET and emits browser/CDN cache separation", async () => {
  clearRuntime();
  const { response, body } = await apiJson(await rankingsRoute.fetch(new Request(
    "https://app.test/api/v19/rankings?market=listed&limit=1&sort=score_desc",
  )));
  assert.equal(response.status, 200);
  assert.equal(body.version, "19.0");
  assert.match(response.headers.get("cache-control") || "", /(?:^|,)\s*no-store(?:,|$)/);
  assert.match(response.headers.get("vercel-cdn-cache-control") || "", /s-maxage=\d+/);
  assert.match(response.headers.get("vercel-cdn-cache-control") || "", /stale-while-revalidate=\d+/);
  assert.equal(response.headers.get("x-twss-api-version"), "19.0");
  assert.equal(allRowRpcCalls().length, 0, "GET must never load the all-row rankings RPC");
  assert.ok(rankingRpcCalls().length >= 1, "GET must use the bounded page RPC");
});

await check("API OPTIONS is empty, CORS-safe and never reaches storage", async () => {
  clearRuntime();
  const response = await rankingsRoute.fetch(new Request("https://app.test/api/v19/rankings", { method: "OPTIONS" }));
  assert.equal(response.status, 204);
  assert.equal(await response.text(), "");
  assert.match(response.headers.get("access-control-allow-methods") || "", /GET/);
  assert.match(response.headers.get("access-control-allow-methods") || "", /OPTIONS/);
  assert.match(response.headers.get("cache-control") || "", /(?:^|,)\s*no-store(?:,|$)/);
  assert.equal(calls.length, 0);
});

await check("API rejects non-GET methods with 405 and no-store", async () => {
  clearRuntime();
  const { response, body } = await apiJson(await homeRoute.fetch(new Request("https://app.test/api/v19/home", {
    method: "POST",
    body: "{}",
    headers: { "content-type": "application/json" },
  })));
  assert.equal(response.status, 405);
  assert.match(response.headers.get("allow") || "", /GET/);
  assert.match(response.headers.get("allow") || "", /OPTIONS/);
  assert.match(response.headers.get("cache-control") || "", /(?:^|,)\s*no-store(?:,|$)/);
  assert.equal(body.error?.code, "method_not_allowed");
  assert.equal(calls.length, 0);
});

await check("ranking limits are bounded and default to the first 10", async () => {
  for (const value of ["0", "101", "1.5", "not-a-number"]) {
    clearRuntime();
    const response = await rankingsRoute.fetch(new Request(`https://app.test/api/v19/rankings?limit=${value}`));
    assert.equal(response.status, 400, `limit=${value}`);
    assert.match(response.headers.get("cache-control") || "", /(?:^|,)\s*no-store(?:,|$)/);
    assert.equal(calls.length, 0);
  }
  clearRuntime();
  const { response, body } = await apiJson(await rankingsRoute.fetch(new Request("https://app.test/api/v19/rankings")));
  assert.equal(response.status, 200);
  assert.equal(body.filters?.limit, 10);
  const args = rpcArguments(rankingRpcCalls()[0].url, rankingRpcCalls()[0].options);
  assert.equal(Number(args.p_limit), 10);
});

await check("cursor locks its filter fingerprint and snapshot dates", async () => {
  clearRuntime();
  const first = await apiJson(await rankingsRoute.fetch(new Request(
    "https://app.test/api/v19/rankings?market=listed&industry=%E5%8D%8A%E5%B0%8E%E9%AB%94%E6%A5%AD&sort=score_desc&limit=1",
  )));
  assert.equal(first.response.status, 200);
  assert.ok(first.body.nextCursor);

  const cursor = encodeURIComponent(first.body.nextCursor);
  const second = await apiJson(await rankingsRoute.fetch(new Request(
    `https://app.test/api/v19/rankings?market=listed&industry=%E5%8D%8A%E5%B0%8E%E9%AB%94%E6%A5%AD&sort=score_desc&limit=2&cursor=${cursor}`,
  )));
  assert.equal(second.response.status, 200, "limit may grow from 10 to 20 without invalidating the cursor");
  const lastPageCall = rankingRpcCalls().at(-1);
  const args = rpcArguments(lastPageCall.url, lastPageCall.options);
  assert.equal(Number(args.p_after_row), 1);
  const lockedDates = typeof args.p_group_dates === "string" ? JSON.parse(args.p_group_dates) : args.p_group_dates;
  assert.equal(lockedDates.listed, "2026-07-15");

  const callsBeforeMismatch = calls.length;
  const mismatch = await apiJson(await rankingsRoute.fetch(new Request(
    `https://app.test/api/v19/rankings?market=otc&industry=%E5%8D%8A%E5%B0%8E%E9%AB%94%E6%A5%AD&sort=score_desc&limit=2&cursor=${cursor}`,
  )));
  assert.equal(mismatch.response.status, 400);
  assert.equal(mismatch.body.error?.code, "invalid_cursor");
  assert.equal(calls.length, callsBeforeMismatch, "invalid cursor must fail before a database request");
});

await check("all v19 ranking sorts are accepted and delegated to the page RPC", async () => {
  const sorts = [
    "score_desc", "score_asc", "confidence_desc", "updated_desc",
    "change_desc", "risk_asc", "risk_desc",
  ];
  for (const sort of sorts) {
    clearRuntime();
    const { response, body } = await apiJson(await rankingsRoute.fetch(new Request(
      `https://app.test/api/v19/rankings?market=listed&limit=3&sort=${sort}`,
    )));
    assert.equal(response.status, 200, sort);
    assert.equal(body.sort, sort);
    assert.equal(allRowRpcCalls().length, 0);
    assert.ok(rankingRpcCalls().length >= 1);
    const args = rpcArguments(rankingRpcCalls()[0].url, rankingRpcCalls()[0].options);
    assert.equal(args.p_sort, sort);
  }
});

await check("AI score remains the existing fixed v16.3 composite", async () => {
  clearRuntime();
  const { response, body } = await apiJson(await rankingsRoute.fetch(new Request(
    "https://app.test/api/v19/rankings?market=listed&search=2330&limit=1",
  )));
  assert.equal(response.status, 200);
  const item = body.items?.[0];
  assert.ok(item);
  const aiValue = typeof item.aiScore === "object" ? item.aiScore.value : item.aiScore;
  const aiBasis = typeof item.aiScore === "object" ? item.aiScore.basis : item.aiScoreBasis;
  assert.equal(item.score, 91.25);
  assert.equal(aiValue, item.score, "confidence must not rescale the frozen composite");
  assert.equal(aiBasis, "v16.3-fixed-weight-composite");
  assert.equal(item.confidence, 72, "confidence remains a separate field");
  if (backend.v19BackendInternals?.deterministicAiScore) {
    assert.equal(backend.v19BackendInternals.deterministicAiScore(80, 10).value, 80);
  }
});

await check("ranking API preserves distinct trade, analysis, fetch, generation and page dates", async () => {
  clearRuntime();
  const { response, body } = await apiJson(await rankingsRoute.fetch(new Request(
    "https://app.test/api/v19/rankings?market=listed&search=2330&limit=1",
  )));
  assert.equal(response.status, 200);
  const item = body.items?.[0];
  const tradeDate = item?.tradeDate ?? item?.dates?.tradeDate;
  const analysisDataDate = item?.analysisDataDate ?? item?.dataDate ?? item?.dates?.analysisDataDate;
  const fetchedAt = item?.fetchedAt ?? item?.dates?.fetchedAt;
  const analysisGeneratedAt = item?.analysisGeneratedAt ?? item?.generatedAt ?? item?.dates?.analysisGeneratedAt;
  const pageUpdatedAt = body.pageUpdatedAt ?? body.dates?.pageUpdatedAt;
  assert.equal(tradeDate, "2026-07-15");
  assert.equal(analysisDataDate, "2026-07-15");
  assert.equal(fetchedAt, FETCHED_AT);
  assert.equal(analysisGeneratedAt, GENERATED_AT);
  assert.equal(pageUpdatedAt, PAGE_UPDATED_AT);
  assert.equal(body.groupStatuses?.listed, "final");
});

await check("stock GET validates symbols without leaking diagnostics", async () => {
  clearRuntime();
  const invalid = await apiJson(await stocksRoute.fetch(new Request("https://app.test/api/v19/stocks/not-a-stock")));
  assert.equal(invalid.response.status, 400);
  assert.equal(invalid.body.error?.code, "invalid_symbol");
  assert.equal(calls.length, 0);

  clearRuntime();
  const valid = await apiJson(await stocksRoute.fetch(new Request("https://app.test/api/v19/stocks/2330")));
  assert.equal(valid.response.status, 200);
  assert.equal(valid.body.symbol, "2330");
  assert.ok(!JSON.stringify(valid.body).includes("sb_publishable_offline_v19_test"));
  assert.equal(allRowRpcCalls().length, 0);
});

await check("ROC dates and Taipei publication times normalize exactly", async () => {
  assert.equal(news.rocDate("1150715"), "2026-07-15");
  assert.equal(news.rocDate("115/07/15"), "2026-07-15");
  assert.equal(news.rocDate("1150231"), null, "invalid calendar dates must not roll into March");
  assert.equal(news.rocDate("bad"), null);
  assert.equal(news.speechTimestamp("1150715", "091530"), "2026-07-15T01:15:30.000Z");
  assert.equal(news.speechTimestamp("1150715", "91530"), "2026-07-15T01:15:30.000Z");
  assert.equal(news.speechTimestamp("1150715", "246000"), null);
});

await check("official-news sentiment is deterministic and auditable", async () => {
  assert.deepEqual(news.classifyDisclosure("獲利成長"), {
    label: "benefit",
    score: 40,
    basis: "official-disclosure-keyword-rule-v1",
    terms: ["獲利", "成長"],
  });
  assert.deepEqual(news.classifyDisclosure("虧損並遭裁罰"), {
    label: "harm",
    score: -40,
    basis: "official-disclosure-keyword-rule-v1",
    terms: ["虧損", "裁罰"],
  });
  assert.equal(news.classifyDisclosure("獲利但有虧損").label, "neutral");
});

await check("official-news hashes are stable and content-sensitive", async () => {
  assert.equal(
    await news.sha256Hex("abc"),
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
  );
  const source = news.OFFICIAL_NEWS_SOURCES.find((item) => item.id === "twse-mops");
  const row = {
    公司代號: "2330",
    公司名稱: "台積電",
    發言日期: "1150715",
    發言時間: "091530",
    出表日期: "1150715",
    主旨: "營收成長",
    說明: "獲利創新高",
    符合條款: "第 4 款",
    事實發生日: "1150714",
  };
  const first = await news.normalizeOfficialDisclosure(row, source, FETCHED_AT);
  const same = await news.normalizeOfficialDisclosure({ ...row }, source, FETCHED_AT);
  const changed = await news.normalizeOfficialDisclosure({ ...row, 說明: "獲利創新高並擴產" }, source, FETCHED_AT);
  assert.ok(first);
  assert.match(first.external_id, /^[a-f0-9]{64}$/);
  assert.match(first.content_hash, /^[a-f0-9]{64}$/);
  assert.equal(first.external_id, same.external_id);
  assert.equal(first.content_hash, same.content_hash);
  assert.equal(first.external_id, changed.external_id, "stable disclosure identity excludes mutable summary text");
  assert.notEqual(first.content_hash, changed.content_hash);
  assert.equal(first.event_date, "2026-07-14");
  assert.equal(first.published_at, "2026-07-15T01:15:30.000Z");
  assert.equal(first.sentiment_label, "benefit");
  assert.equal(first.fetched_at, FETCHED_AT);
  assert.equal(first.source_url, source.url);
});

const [backendSource, migration, config, newsWorker] = await Promise.all([
  read("src/v19-backend.js"),
  read("supabase/migrations/20260716003204_add_v19_read_models.sql"),
  read("supabase/config.toml"),
  read("supabase/functions/twss-v19-news/index.ts"),
]);

await check("backend source uses only the bounded rankings page RPC", async () => {
  assert.match(backendSource, /twss_v19_rankings_page/);
  assert.doesNotMatch(backendSource, /twss_v19_current_rankings/);
});

await check("migration enables RLS and pairs policies with explicit grants", async () => {
  for (const table of ["v19_ranking_snapshots", "v19_news_items"]) {
    assert.match(migration, new RegExp(`alter\\s+table\\s+public\\.${table}\\s+enable\\s+row\\s+level\\s+security`, "i"));
    assert.match(migration, new RegExp(`create\\s+policy\\s+${table}_[a-z_]*read`, "i"));
    assert.match(migration, new RegExp(`grant\\s+select(?:\\s*\\([^)]*\\))?\\s+on\\s+table\\s+public\\.${table}\\s+to\\s+anon,\\s*authenticated`, "is"));
    assert.match(migration, new RegExp(`grant\\s+all\\s+on\\s+table\\s+public\\.${table}\\s+to\\s+service_role`, "i"));
  }
});

await check("every v19 SECURITY DEFINER has an empty search_path and revoked PUBLIC execute", async () => {
  const declaration = /create\s+or\s+replace\s+function\s+public\.([a-z0-9_]+)\s*\([\s\S]*?\)\s*returns[\s\S]*?as\s+\$\$/gi;
  let match;
  let definerCount = 0;
  while ((match = declaration.exec(migration))) {
    const header = match[0];
    if (!/security\s+definer/i.test(header)) continue;
    definerCount += 1;
    assert.match(header, /set\s+search_path\s*=\s*''/i, match[1]);
    assert.match(migration, new RegExp(`revoke\\s+all\\s+on\\s+function\\s+public\\.${match[1]}\\s*\\(`, "i"), match[1]);
  }
  assert.ok(definerCount >= 3, "expected ranking refresh, trigger/status and scheduled refresh definers");
  assert.match(migration, /twss_v19_rankings_page[\s\S]*?security\s+invoker[\s\S]*?set\s+search_path\s*=\s*''/i);
});

await check("news Edge Function keeps JWT bypass explicit but verifies the internal token", async () => {
  const section = config.match(/\[functions\.twss-v19-news\]([\s\S]*?)(?=\n\[|$)/)?.[1] || "";
  assert.match(section, /verify_jwt\s*=\s*false/);
  assert.match(section, /entrypoint\s*=\s*"\.\/functions\/twss-v19-news\/index\.ts"/);
  assert.match(newsWorker, /x-twss-sync-token/);
  assert.match(newsWorker, /twss_verify_sync_token/);
  assert.doesNotMatch(newsWorker, /console\.(?:log|error)\([^\n]*(?:token|ADMIN_KEY)/i);
});

await check("news sync skips unchanged content instead of rewriting it", async () => {
  const combined = `${newsWorker}\n${migration}`;
  assert.match(combined, /content_hash/);
  const hasWorkerSkip = /unchanged(?:Count|_count|\s*=|\s*:|\s*\))/i.test(newsWorker) &&
    /existing|known|previous/i.test(newsWorker);
  const hasConflictGuard = /on\s+conflict[\s\S]*?do\s+update[\s\S]*?where[\s\S]*?content_hash\s+is\s+distinct\s+from/is.test(migration);
  assert.ok(hasWorkerSkip || hasConflictGuard, "identical source/external_id/content_hash rows must be skipped");
});

await check("official ranks cannot be shifted by higher non-official rows", async () => {
  assert.doesNotMatch(
    migration,
    /case\s+when\s+h\.official\s+then\s+rank\(\)\s+over\s*\(\s*order\s+by\s+h\.score/gi,
    "CASE outside a window still lets non-official rows participate in rank()",
  );
  const safeOfficialRanking = /where[\s\S]{0,180}\bh\.official\b[\s\S]{0,220}rank\(\)\s+over/i.test(migration) ||
    /rank\(\)\s+over\s*\([^)]*partition\s+by\s+h\.official/is.test(migration) ||
    /current_official_rank(?:ed|s)|previous_official_rank(?:ed|s)/i.test(migration) ||
    /order\s+by\s+h\.official\s+desc[\s\S]{0,160}h\.score/i.test(migration);
  assert.ok(safeOfficialRanking, "rank window must isolate official rows before assigning official ranks");
});

await check("migration keeps AI score as the fixed composite and stores every date dimension", async () => {
  assert.match(migration, /ai_score_basis\s+text\s+not\s+null\s+default\s+'v16\.3-fixed-weight-composite'/i);
  assert.match(migration, /\bh\.score,\s*'v16\.3-fixed-weight-composite',\s*case\s+when/is);
  for (const column of ["trade_date", "source_fetched_at", "source_updated_at", "generated_at"]) {
    assert.match(migration, new RegExp(`\\b${column}\\b`, "i"));
  }
});

await check("ranking and news cron jobs are idempotently replaced and token-protected", async () => {
  for (const job of ["twss-v19-ranking-snapshots", "twss-v19-news"]) {
    assert.match(migration, new RegExp(`jobname\\s*=\\s*'${job}'`, "i"));
    assert.match(migration, new RegExp(`cron\\.schedule\\(\\s*'${job}'`, "i"));
  }
  assert.match(migration, /cron\.unschedule\s*\(/i);
  assert.match(migration, /vault\.decrypted_secrets[\s\S]*?name\s*=\s*'twss_sync_token'/i);
  assert.match(migration, /x-twss-sync-token/i);
  assert.doesNotMatch(migration, /eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9/);
  assert.doesNotMatch(migration, /service_role(?:_key)?\s*[:=]\s*['"][^'"]+/i);
});

await check("v19 migration is additive and does not move existing schema", async () => {
  assert.doesNotMatch(migration, /\bdrop\s+table\b/i);
  assert.doesNotMatch(migration, /\btruncate\b/i);
  assert.doesNotMatch(migration, /\balter\s+table\s+\S+\s+rename\b/i);
  assert.doesNotMatch(migration, /\binsert\s+into\s+(?!public\.(?:v19_|stock_sync_state))/i);
});

if (failures.length) {
  console.error(`v19 contract: ${checks.length} passed, ${failures.length} failed (${root})`);
  process.exitCode = 1;
} else {
  console.log(`v19 contract: ${checks.length} passed, 0 failed`);
}
