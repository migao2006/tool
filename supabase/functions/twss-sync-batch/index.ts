// Taiwan Stock Smart v16.3 persistent batch updater.
// Called only by pg_cron with a token generated and retained in Supabase Vault.
// @ts-ignore JavaScript modules are shared with the Vercel runtime.
import {
  ANALYSIS_VERSION,
  buildBenchmarks,
  buildDeepData,
  buildPriceHistory,
  buildTdccSnapshot,
} from "../../../src/deep-data.js";
// @ts-ignore JavaScript modules are shared with the Vercel runtime.
import { handleMarketData } from "../../../src/market-data.js";
// @ts-ignore JavaScript modules are shared with the Vercel runtime.
import { buildPeerContexts, scoreOpportunity } from "../../../src/opportunity-engine.js";

const VERSION = "16.3";
const PROJECT_URL = Deno.env.get("SUPABASE_URL") || "";
const FINMIND_AUTHENTICATED = Boolean(Deno.env.get("FINMIND_TOKEN"));
const FINMIND_HOURLY_LIMIT = FINMIND_AUTHENTICATED ? 600 : 300;
const GROUPS = ["listed", "otc", "etf"] as const;
type Group = typeof GROUPS[number];

function adminKey() {
  try {
    const keys = JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") || "{}");
    if (keys.default) return String(keys.default);
  } catch {}
  return Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
}

const ADMIN_KEY = adminKey();
const json = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), {
  status,
  headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
});
const finite = (value: unknown) => value != null && Number.isFinite(Number(value));
const now = () => new Date().toISOString();

async function logAdminHealth(mode: "universe" | "deep", result: unknown, group: Group | null = null) {
  const row = result && typeof result === "object" && !Array.isArray(result)
    ? result as Record<string, any>
    : {};
  const failureCount = Array.isArray(row.failures) ? row.failures.length : 0;
  const [healthResult, missingResult] = await Promise.allSettled([
    rest("rpc/twss_public_data_health", { method: "POST", body: {} }),
    rest("rpc/twss_public_missing_data", { method: "POST", body: { p_limit: 20 } }),
  ]);
  console.info("[admin-data-health]", {
    mode,
    group,
    status: row.skipped ? "skipped" : failureCount ? "partial" : "success",
    date: row.date || row.dataDate || null,
    total: finite(row.total) ? Number(row.total) : null,
    verified: finite(row.verified) ? Number(row.verified) : null,
    remaining: finite(row.remaining) ? Number(row.remaining) : null,
    failures: failureCount,
    health: healthResult.status === "fulfilled"
      ? healthResult.value.data
      : { status: "unavailable" },
    missingData: missingResult.status === "fulfilled"
      ? missingResult.value.data
      : { status: "unavailable" },
    loggedAt: now(),
  });
}

async function rest(path: string, options: {
  method?: string;
  body?: unknown;
  prefer?: string;
  count?: boolean;
} = {}) {
  if (!PROJECT_URL || !ADMIN_KEY) throw new Error("Supabase backend environment is incomplete");
  const headers: Record<string, string> = {
    accept: "application/json",
    "content-type": "application/json",
    apikey: ADMIN_KEY,
  };
  if (!ADMIN_KEY.startsWith("sb_secret_")) headers.authorization = `Bearer ${ADMIN_KEY}`;
  if (options.prefer) headers.prefer = options.prefer;
  if (options.count) headers.prefer = [headers.prefer, "count=exact"].filter(Boolean).join(",");
  const response = await fetch(`${PROJECT_URL}/rest/v1/${path}`, {
    method: options.method || "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(`Database ${response.status}: ${message.slice(0, 500)}`);
  }
  if (options.method === "HEAD" || response.status === 204) return { data: null, response };
  const text = await response.text();
  return { data: text ? JSON.parse(text) : null, response };
}

async function verifyRequest(req: Request) {
  const token = req.headers.get("x-twss-sync-token") || "";
  if (!token) return false;
  const { data } = await rest("rpc/twss_verify_sync_token", {
    method: "POST",
    body: { p_token: token },
  });
  return data === true;
}

async function upsert(table: string, rows: Record<string, unknown>[], conflict: string, chunkSize = 200) {
  if (!rows.length) return;
  for (let index = 0; index < rows.length; index += chunkSize) {
    const chunk = rows.slice(index, index + chunkSize);
    // PostgREST requires every object in a bulk insert to expose the same keys.
    // Market sources legitimately omit optional fields, so preserve that fact as
    // SQL null instead of allowing JSON.stringify to remove the property.
    const keys = [...new Set(chunk.flatMap((row) => Object.keys(row)))];
    const normalized = chunk.map((row) => Object.fromEntries(
      keys.map((key) => [key, row[key] === undefined ? null : row[key]]),
    ));
    await rest(`${table}?on_conflict=${encodeURIComponent(conflict)}`, {
      method: "POST",
      body: normalized,
      prefer: "resolution=merge-duplicates,return=minimal",
    });
  }
}

async function patchState(jobKey: string, values: Record<string, unknown>) {
  await rest(`stock_sync_state?job_key=eq.${encodeURIComponent(jobKey)}`, {
    method: "PATCH",
    body: { ...values, updated_at: now() },
    prefer: "return=minimal",
  });
}

async function finalizeRankingCycle(group: Group, date: string, total: number) {
  const attemptedAt = now();
  try {
    const { data } = await rest("rpc/twss_finalize_ranking_cycle", {
      method: "POST",
      body: {
        p_group_name: group,
        p_score_date: date,
        p_model_version: VERSION,
        p_expected_count: Math.max(0, Math.round(total)),
      },
    });
    let backtest: unknown = null;
    try {
      const evaluated = await rest("rpc/twss_evaluate_matured_backtests", {
        method: "POST",
        body: { p_group_name: group, p_model_version: VERSION },
      });
      backtest = evaluated.data || null;
    } catch (error) {
      // The evaluator uses only stored prices and scores.  It is observational
      // and must not turn a completed market sync into a failed cycle.
      backtest = { status: "error", error: error instanceof Error ? error.message : String(error) };
      console.error("[ranking-backtest] evaluation failed", { group, date, error: backtest });
    }
    return { status: "final", attemptedAt, result: data || null, backtest };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    // Ranking history is an observation layer.  A transient finalization
    // failure must never roll back the completed market-data synchronization.
    console.error("[ranking-cycle] finalization failed", { group, date, error: message });
    return { status: "error", attemptedAt, error: message.slice(0, 1000) };
  }
}

async function getState(jobKey: string) {
  const { data } = await rest(`stock_sync_state?select=*&job_key=eq.${encodeURIComponent(jobKey)}&limit=1`);
  return Array.isArray(data) ? data[0] : null;
}

async function claimLease(jobKey: string, owner: string, seconds = 180) {
  const { data } = await rest("rpc/twss_claim_sync_lease", {
    method: "POST",
    body: { p_job_key: jobKey, p_owner: owner, p_seconds: seconds },
  });
  return data === true;
}

async function releaseLease(jobKey: string, owner: string) {
  await rest("rpc/twss_release_sync_lease", {
    method: "POST",
    body: { p_job_key: jobKey, p_owner: owner },
  });
}

async function withLease(jobKey: string, task: () => Promise<unknown>) {
  const owner = crypto.randomUUID();
  if (!await claimLease(jobKey, owner)) {
    return { skipped: true, reason: "active-lease", jobKey };
  }
  try {
    return await task();
  } catch (error) {
    await patchState(jobKey, {
      status: "error",
      last_error: error instanceof Error ? error.message.slice(0, 2000) : String(error).slice(0, 2000),
      next_run_at: new Date(Date.now() + 20 * 60 * 1_000).toISOString(),
    }).catch(() => undefined);
    throw error;
  } finally {
    await releaseLease(jobKey, owner).catch(() => undefined);
  }
}

async function reserveFinmindBatch(
  itemCosts: number[],
  overhead: number,
  claimCap: number,
  metadata: Record<string, unknown>,
) {
  const { data } = await rest("rpc/twss_reserve_api_batch", {
    method: "POST",
    body: {
      p_source: "finmind",
      p_item_costs: itemCosts,
      p_overhead: Math.max(0, Math.round(overhead)),
      p_hourly_limit: FINMIND_HOURLY_LIMIT,
      p_claim_cap: Math.max(0, Math.round(claimCap)),
      p_metadata: { version: VERSION, ...metadata },
    },
  });
  return data && typeof data === "object" ? data : {
    items: 0,
    claimed: 0,
    remaining: 0,
    retryAfterAt: null,
  };
}

async function storedHistory(symbol: string, limit = 280) {
  const params = new URLSearchParams({
    select: "trade_date,open,high,low,close,volume,trade_value,transactions",
    symbol: `eq.${symbol}`,
    order: "trade_date.desc",
    limit: String(Math.max(20, Math.min(300, limit))),
  });
  const { data } = await rest(`stock_price_history?${params}`);
  return (Array.isArray(data) ? data : []).reverse().map((row: Record<string, any>) => ({
    date: row.trade_date,
    open: finite(row.open) ? Number(row.open) : null,
    high: finite(row.high) ? Number(row.high) : null,
    low: finite(row.low) ? Number(row.low) : null,
    close: finite(row.close) ? Number(row.close) : null,
    volume: finite(row.volume) ? Number(row.volume) : null,
    value: finite(row.trade_value) ? Number(row.trade_value) : null,
    transactions: finite(row.transactions) ? Number(row.transactions) : null,
  })).filter((row: Record<string, any>) =>
    row.close != null && row.high != null && row.low != null);
}

async function mergeLatestOfficialSnapshot(symbol: string, history: Record<string, any>[]) {
  const { data } = await rest(
    `stock_snapshots?select=trade_date,open,high,low,close,volume,trade_value,transactions&symbol=eq.${encodeURIComponent(symbol)}&order=trade_date.desc&limit=1`,
  );
  const snapshot = Array.isArray(data) ? data[0] : null;
  if (!snapshot || !finite(snapshot.close) || !finite(snapshot.high) || !finite(snapshot.low)) return history;
  const official = {
    date: String(snapshot.trade_date),
    open: finite(snapshot.open) ? Number(snapshot.open) : Number(snapshot.close),
    high: Number(snapshot.high),
    low: Number(snapshot.low),
    close: Number(snapshot.close),
    volume: finite(snapshot.volume) ? Number(snapshot.volume) : null,
    value: finite(snapshot.trade_value) ? Number(snapshot.trade_value) : null,
    transactions: finite(snapshot.transactions) ? Number(snapshot.transactions) : null,
    source: "TWSE/TPEx official snapshot",
  };
  const merged = new Map(history.map((row) => [String(row.date), row]));
  merged.set(official.date, { ...(merged.get(official.date) || {}), ...official });
  return [...merged.values()].sort((left, right) => String(left.date).localeCompare(String(right.date))).slice(-280);
}

function completedHistoryAttempt(state: Record<string, any> | null) {
  // A successful empty/short response is also a real source result (typically
  // a newly listed security).  Persist that fact so reopening the modal does
  // not burn one API unit forever trying to manufacture unavailable history.
  return state?.details?.historyComplete === true;
}

function historyPayload(symbol: string, history: Record<string, any>[], source: string) {
  return {
    mode: history.length >= 120 ? "live" : "partial",
    symbol,
    source,
    count: history.length,
    period: history.at(-1)?.date || null,
    history,
  };
}

async function serveOnDemandHistory(url: URL) {
  const symbol = String(url.searchParams.get("symbol") || "").trim().toUpperCase();
  if (!/^\d{4,6}[A-Z]?$/i.test(symbol)) return json({ error: "股票代號格式不正確" }, 400);
  const requestedMonths = Math.max(6, Math.min(24, Number(url.searchParams.get("months")) || 18));
  const jobKey = `history_${symbol}`;
  let [existing, state] = await Promise.all([storedHistory(symbol), getState(jobKey)]);
  existing = await mergeLatestOfficialSnapshot(symbol, existing);
  if (existing.length >= 120 || completedHistoryAttempt(state)) {
    console.info("[public-history] database hit", { symbol, rows: existing.length });
    return json(historyPayload(symbol, existing, "Supabase 後端歷史資料庫"));
  }
  const { data: masterRows } = await rest(
    `stock_master?select=symbol,market&symbol=eq.${encodeURIComponent(symbol)}&limit=1`,
  );
  const master = Array.isArray(masterRows) ? masterRows[0] : null;
  if (!master) return json({ error: `${symbol} 不在目前台股標的清單` }, 404);
  if (!state) {
    await rest("stock_sync_state?on_conflict=job_key", {
      method: "POST",
      body: [{ job_key: jobKey, group_name: "history", status: "pending", details: { symbol } }],
      prefer: "resolution=ignore-duplicates,return=minimal",
    });
  }
  const owner = crypto.randomUUID();
  if (!await claimLease(jobKey, owner, 180)) {
    return json({
      mode: "pending",
      pending: true,
      code: "HISTORY_IN_PROGRESS",
      symbol,
      count: existing.length,
      error: `${symbol} 歷史日線正在補抓，完成後重新開啟即可`,
    }, 202);
  }
  try {
    [existing, state] = await Promise.all([storedHistory(symbol), getState(jobKey)]);
    existing = await mergeLatestOfficialSnapshot(symbol, existing);
    if (existing.length >= 120 || completedHistoryAttempt(state)) {
      return json(historyPayload(symbol, existing, "Supabase 後端歷史資料庫"));
    }
    const budget = await reserveFinmindBatch([1], 0, 1, {
      job: "public_history",
      symbol,
      requestedMonths,
    });
    if (Number(budget.items) < 1) {
      console.info("[public-history] quota pending", { symbol, retryAfterAt: budget.retryAfterAt || null });
      return json({
        mode: "pending",
        pending: true,
        code: "HISTORY_PENDING",
        symbol,
        count: existing.length,
        retryAfterAt: budget.retryAfterAt || null,
        error: `${symbol} 歷史日線正在等待 API 配額，請稍後重新開啟`,
      }, 202);
    }
    console.info("[public-history] fetching", { symbol, requestedMonths });
    const payload = await buildPriceHistory(symbol, master.market || "上市", requestedMonths, {
      // The shared ledger reserved exactly one request.  A later user action can
      // retry a transient failure without silently exceeding the hourly ceiling.
      finmindRetries: 0,
    });
    const history = await mergeLatestOfficialSnapshot(symbol, payload.history || []);
    const updatedAt = now();
    await upsert("stock_price_history", history.map((row: Record<string, any>) => ({
      symbol,
      trade_date: row.date,
      open: row.open,
      high: row.high,
      low: row.low,
      close: row.close,
      volume: row.volume,
      trade_value: row.value,
      transactions: finite(row.transactions) ? Math.round(Number(row.transactions)) : null,
      source: row.source || "FinMind TaiwanStockPrice on-demand",
      updated_at: updatedAt,
    })), "symbol,trade_date");
    await patchState(jobKey, {
      status: "success",
      last_error: null,
      last_success_at: updatedAt,
      details: {
        symbol,
        historyComplete: true,
        historyRows: history.length,
        historyPeriod: history.at(-1)?.date || null,
      },
    });
    console.info("[public-history] persisted", { symbol, rows: history.length, period: history.at(-1)?.date || null });
    return json(historyPayload(symbol, history, "FinMind 按需補抓（已存入 Supabase）"));
  } catch (error) {
    await patchState(jobKey, {
      status: "error",
      last_error: error instanceof Error ? error.message.slice(0, 500) : String(error).slice(0, 500),
    }).catch(() => undefined);
    throw error;
  } finally {
    await releaseLease(jobKey, owner).catch(() => undefined);
  }
}

async function localPayload(type: string) {
  const url = new URL(`https://sync.internal/api/market-data?type=${type}&refresh=1`);
  const response = await handleMarketData(new Request(url), url);
  const payload = await response.json();
  if (!response.ok) throw new Error(`${type}: ${payload.error || response.status}`);
  return payload;
}

function groupOf(stock: Record<string, any>): Group {
  if (stock.instrumentType === "ETF" || /^00\d{2,4}[A-Z]?$/i.test(String(stock.symbol || ""))) return "etf";
  return stock.market === "上櫃" ? "otc" : "listed";
}

function provisionalScore(stock: Record<string, any>, group: Group) {
  const liquidity = Math.min(25, Math.max(0, (Math.log10(Math.max(Number(stock.value) || 1, 1)) - 6) * 8));
  const valuation = Number(stock.pe) > 0 ? Math.max(0, 14 - Number(stock.pe) * 0.25) : 3;
  const chip = stock.inst == null || !stock.volume ? 0 : Math.max(-8, Math.min(12, Number(stock.inst) / Number(stock.volume) * 30));
  if (group === "etf") {
    return liquidity * 2 + Math.max(-10, Math.min(20, (Number(stock.change) || 0) * 3)) + Math.min(15, (Number(stock.yield) || 0) * 2);
  }
  const growth = finite(stock.rev) ? Math.max(-10, Math.min(35, Number(stock.rev) * 0.75 + 12)) : 0;
  const acceleration = finite(stock.revAcceleration) ? Math.max(-8, Math.min(18, Number(stock.revAcceleration) * 0.8)) : 0;
  const quality = finite(stock.roe) ? Math.max(-5, Math.min(18, Number(stock.roe))) : Number(stock.eps) > 0 ? 7 : 0;
  return growth + acceleration + quality + valuation + chip + liquidity * (group === "otc" ? 0.8 : 0.55);
}

function passesPreflight(stock: Record<string, any>, group: Group) {
  const floor = group === "otc"
    ? { volume: 100, value: 10_000_000 }
    : group === "etf"
      ? { volume: 500, value: 20_000_000 }
      : { volume: 300, value: 20_000_000 };
  return !stock.hardExcluded && finite(stock.close) &&
    finite(stock.volume) && Number(stock.volume) >= floor.volume &&
    finite(stock.value) && Number(stock.value) >= floor.value;
}

function compactStock(stock: Record<string, any>) {
  const keys = [
    "symbol", "name", "market", "instrumentType", "industry", "close", "change", "open", "high", "low",
    "volume", "value", "transactions", "pe", "pb", "yield", "revenue", "revenuePreviousMonth",
    "revenueLastYearMonth", "revenueYtd", "revenueLastYearYtd", "rev", "revMom", "revYtd", "revAcceleration",
    "revPeriod", "roe", "roePeriod", "eps", "grossMargin", "operatingMargin", "netMargin", "debt",
    "roeEstimated", "equityRatio", "revenueUnit", "quarterRevenue", "quarterRevenueUnit", "quarterRevenuePeriod", "dataStatus", "priceDate",
    "foreign", "trust", "dealer", "inst", "marginBalance", "marginChange", "shortBalance", "shortChange", "risk",
  ];
  return Object.fromEntries(keys.map((key) => [key, stock[key]]).filter(([, value]) => value !== undefined));
}

function compactSourceDiagnostics(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const allowed = [
    "label", "status", "statusCode", "rows", "retryable", "reusedFromStatus",
    "expectedPeriod", "actualPeriod",
  ];
  return Object.fromEntries(Object.entries(value as Record<string, any>).map(([key, diagnostic]) => [
    key,
    diagnostic && typeof diagnostic === "object" && !Array.isArray(diagnostic)
      ? Object.fromEntries(allowed
        .filter((field) => diagnostic[field] !== undefined)
        .map((field) => [field, diagnostic[field]]))
      : {},
  ]));
}

function compactDeep(deep: Record<string, any>) {
  return {
    analysisVersion: deep.analysisVersion,
    symbol: deep.symbol,
    instrumentType: deep.instrumentType,
    market: deep.market,
    source: deep.source,
    fetchedAt: deep.fetchedAt,
    price: deep.price,
    benchmarkCoverage: deep.benchmarkCoverage,
    sourceDiagnostics: compactSourceDiagnostics(deep.sourceDiagnostics),
    revenue: deep.revenue,
    financial: deep.financial ? { ...deep.financial, history: undefined } : undefined,
    institutional: deep.institutional ? { ...deep.institutional, history: undefined } : undefined,
    margin: deep.margin ? { ...deep.margin, history: undefined } : undefined,
    lending: deep.lending,
    holdings: deep.holdings,
    etf: deep.etf,
    reused: deep.reused,
    missing: deep.missing,
  };
}

function reusableDiagnostic(analysis: Record<string, any> | null | undefined, key: string) {
  return ["ok", "reused"].includes(String(analysis?.sourceDiagnostics?.[key]?.status || ""));
}

function analysisRepairReasons(deep: Record<string, any>, group: Group) {
  if (group === "etf") return [];
  const essential = ["revenue", "income", "balance", "cashflow", "institutional", "margin"];
  const reasons = essential.filter((key) =>
    ["empty-no-history", "stale-source-period"].includes(String(deep?.sourceDiagnostics?.[key]?.status || "")));
  const coverage = deep?.financial?.sourceCoverage || {};
  if (["incomeRows", "balanceRows", "cashflowRows"].some((key) => Number(coverage[key]) <= 0)) {
    reasons.push("financial-source-coverage");
  }
  return [...new Set(reasons)];
}

async function syncUniverseUnlocked() {
  await patchState("universe", { status: "running", started_at: now(), last_error: null });
  try {
    // Reserve the two historical-index fallbacks before any FinMind call.  If
    // the rolling-hour budget is full, official TWSE/TPEx index rows still run
    // and the next deep batch can retry the missing historical benchmark.
    const benchmarkBudget = await reserveFinmindBatch([2], 0, 2, { job: "universe" });
    const allowBenchmarkFallback = Number(benchmarkBudget.items) === 1;
    const [stocksPayload, revenuePayload, financialPayload, holdingsPayload, benchmarksPayload, accumulatedRows] = await Promise.all([
      localPayload("stocks"),
      localPayload("revenue"),
      localPayload("financials"),
      // TDCC is a large weekly CSV.  One slow response used to consume the
      // entire 150-second Edge wall-clock budget because its generic retry
      // policy could wait twice for 60 seconds.  The daily universe is allowed
      // one bounded attempt; a later run fills holdings without blocking all
      // prices, revenue and financial data.
      buildTdccSnapshot({ timeout: 20_000, retries: 0 }).catch((error: unknown) => ({
        bySymbol: {},
        date: "",
        error: error instanceof Error ? error.message : String(error),
      })),
      buildBenchmarks({
        finmindRetries: 0,
        officialRetries: 0,
        officialTimeout: 20_000,
        allowFinmind: allowBenchmarkFallback,
      }).catch((error: unknown) => ({
        listed: [],
        otc: [],
        coverage: { listed: false, otc: false },
        error: error instanceof Error ? error.message : String(error),
      })),
      rest("stock_analysis_cache?select=symbol,stock&status=eq.ready&limit=2000")
        .then((result) => Array.isArray(result.data) ? result.data : [])
        .catch(() => []),
    ]);
    const merged = new Map<string, Record<string, any>>(
      (stocksPayload.stocks || []).map((stock: Record<string, any>) => [String(stock.symbol), { ...stock }]),
    );
    for (const row of [...(revenuePayload.fundamentals || []), ...(financialPayload.fundamentals || [])]) {
      const current = merged.get(String(row.symbol));
      if (current) Object.assign(current, row);
    }
    // Official cross-section feeds occasionally omit a company even though its
    // current period was already verified through deep history.  Preserve that
    // accumulated value instead of turning it back into a missing field at the
    // next daily universe refresh.
    for (const row of accumulatedRows) {
      const current = merged.get(String(row.symbol));
      const stored = row.stock || {};
      if (!current || !finite(stored.revenue)) continue;
      if (!finite(current.revenue) || String(stored.revPeriod || "") >= String(current.revPeriod || "")) {
        Object.assign(current, Object.fromEntries(
          [
            "revenue", "revenuePreviousMonth", "revenueLastYearMonth", "revenueYtd", "revenueLastYearYtd",
            "rev", "revMom", "revYtd", "revAcceleration", "revPeriod",
          ].map((key) => [key, stored[key]]).filter(([, value]) => value !== undefined),
        ));
      }
    }
    const stocks = [...merged.values()];
    if (stocks.length < 100) throw new Error(`Universe coverage too low: ${stocks.length}`);
    const contexts = buildPeerContexts(stocks);
    const dataDate = stocksPayload.date || new Date().toISOString().slice(0, 10);
    const groupDates = {
      listed: stocksPayload.dates?.price?.twse || dataDate,
      otc: stocksPayload.dates?.price?.tpex || dataDate,
      etf: stocksPayload.dates?.price?.twse || dataDate,
    };
    const revenueMap = new Map(
      (revenuePayload.fundamentals || []).map((row: Record<string, any>) => [String(row.symbol), row]),
    );
    const financialMap = new Map(
      (financialPayload.fundamentals || []).map((row: Record<string, any>) => [String(row.symbol), row]),
    );
    const sourceDiagnostics = {
      stocks: {
        count: stocks.length,
        markets: stocksPayload.markets || {},
        dates: stocksPayload.dates || {},
        sourceStatus: stocksPayload.sourceStatus || {},
      },
      revenue: {
        period: revenuePayload.period || null,
        publishedAt: revenuePayload.publishedAt || null,
        rows: revenueMap.size,
        accumulatedDeepRows: accumulatedRows.filter((row: Record<string, any>) => finite(row.stock?.revenue)).length,
        matched: stocks.filter((stock) => groupOf(stock) !== "etf" && revenueMap.has(String(stock.symbol))).length,
        missingAmount: stocks.filter((stock) => groupOf(stock) !== "etf" && !finite(stock.revenue)).length,
        eligibleMissingAmount: stocks.filter((stock) => {
          const group = groupOf(stock);
          return group !== "etf" && !finite(stock.revenue) && passesPreflight(stock, group);
        }).length,
        excludedMissingAmount: stocks.filter((stock) => {
          const group = groupOf(stock);
          return group !== "etf" && !finite(stock.revenue) && !passesPreflight(stock, group);
        }).length,
        yoyNotApplicable: stocks.filter((stock) =>
          groupOf(stock) !== "etf" && !finite(stock.rev) &&
          finite(stock.revenueLastYearMonth) && Number(stock.revenueLastYearMonth) === 0).length,
        dates: revenuePayload.dates || {},
        sourceStatus: revenuePayload.sourceStatus || {},
        coverage: revenuePayload.coverage || {},
      },
      financial: {
        period: financialPayload.period || null,
        publishedAt: financialPayload.publishedAt || null,
        rows: financialMap.size,
        matched: stocks.filter((stock) => groupOf(stock) !== "etf" && financialMap.has(String(stock.symbol))).length,
        dates: financialPayload.dates || {},
        sourceStatus: financialPayload.sourceStatus || {},
        coverage: financialPayload.coverage || {},
      },
      holdings: {
        date: holdingsPayload.date || null,
        rows: Object.keys(holdingsPayload.bySymbol || {}).length,
        error: holdingsPayload.error || null,
      },
      benchmarks: {
        coverage: benchmarksPayload.coverage || {},
        source: benchmarksPayload.source || {},
        error: benchmarksPayload.error || null,
      },
      preflight: Object.fromEntries(GROUPS.map((group) => {
        const groupRows = stocks.filter((stock) => groupOf(stock) === group);
        const eligible = groupRows.filter((stock) => passesPreflight(stock, group)).length;
        return [group, { total: groupRows.length, eligible, excluded: groupRows.length - eligible }];
      })),
    };
    const updatedAt = now();
    const masters = stocks.map((stock) => ({
      symbol: String(stock.symbol),
      name: stock.name || String(stock.symbol),
      market: stock.market || "上市",
      industry: stock.industry || "未分類",
      security_type: groupOf(stock) === "etf" ? "ETF" : "股票",
      source: stock.market === "上櫃" ? "TPEx" : "TWSE",
      active: true,
      last_trade_date: groupDates[groupOf(stock)] || dataDate,
      metadata: { instrumentType: stock.instrumentType || (groupOf(stock) === "etf" ? "ETF" : "股票") },
      updated_at: updatedAt,
    }));
    await upsert("stock_master", masters, "symbol");
    const snapshots = stocks.map((stock) => {
      const group = groupOf(stock);
      const priceDate = groupDates[group] || dataDate;
      const revenueRow = revenueMap.get(String(stock.symbol));
      const dataStatus = group === "etf" ? {
        revenue: "not-applicable",
        financial: "not-applicable",
      } : {
        revenue: finite(stock.revenue)
          ? "available"
          : revenueRow ? "source-row-incomplete" : "source-not-returned",
        revenueYoy: finite(stock.rev)
          ? "available"
          : finite(stock.revenueLastYearMonth) && Number(stock.revenueLastYearMonth) === 0
            ? "not-applicable-prior-year-zero"
            : "missing",
        financial: financialMap.has(String(stock.symbol)) ? "available" : "source-not-returned",
        quarterRevenue: finite(stock.quarterRevenue)
          ? "available"
          : financialMap.has(String(stock.symbol)) ? "source-row-incomplete-or-not-comparable" : "source-not-returned",
      };
      const peerContext = {
        ...(contexts[String(stock.symbol)] || {}),
        holdings: holdingsPayload.bySymbol?.[String(stock.symbol)] || null,
      };
      return {
        symbol: String(stock.symbol),
        trade_date: priceDate,
        market: stock.market || "上市",
        industry: stock.industry || "未分類",
        instrument_type: group === "etf" ? "ETF" : "股票",
        open: stock.open,
        high: stock.high,
        low: stock.low,
        close: stock.close,
        change_pct: stock.change,
        volume: finite(stock.volume) ? Math.round(Number(stock.volume)) : null,
        trade_value: stock.value,
        transactions: finite(stock.transactions) ? Math.round(Number(stock.transactions)) : null,
        pe: stock.pe,
        pb: stock.pb,
        dividend_yield: stock.yield,
        revenue_growth: stock.rev,
        eps: stock.eps,
        roe: stock.roe,
        debt_ratio: stock.debt,
        foreign_buy: finite(stock.foreign) ? Math.round(Number(stock.foreign)) : null,
        trust_buy: finite(stock.trust) ? Math.round(Number(stock.trust)) : null,
        dealer_buy: finite(stock.dealer) ? Math.round(Number(stock.dealer)) : null,
        institutional_buy: finite(stock.inst) ? Math.round(Number(stock.inst)) : null,
        margin_balance: finite(stock.marginBalance) ? Math.round(Number(stock.marginBalance)) : null,
        margin_change: finite(stock.marginChange) ? Math.round(Number(stock.marginChange)) : null,
        short_balance: finite(stock.shortBalance) ? Math.round(Number(stock.shortBalance)) : null,
        short_change: finite(stock.shortChange) ? Math.round(Number(stock.shortChange)) : null,
        is_disposition: Boolean(stock.disp),
        is_full_delivery: Boolean(stock.full),
        preliminary_score: passesPreflight(stock, group)
          ? Number(provisionalScore(stock, group).toFixed(4))
          : null,
        peer_context: peerContext,
        raw_data: compactStock({ ...stock, dataStatus, priceDate }),
        source_dates: {
          price: priceDate,
          revenue: stock.revPeriod || revenuePayload.period || null,
          financial: stock.roePeriod || financialPayload.period || null,
          dataStatus,
        },
        source: stock.market === "上櫃" ? "TPEx/TWSE/FinMind" : "TWSE/FinMind",
        updated_at: updatedAt,
      };
    });
    await upsert("stock_snapshots", snapshots, "symbol,trade_date", 150);
    const counts = Object.fromEntries(GROUPS.map((group) => [group, stocks.filter((stock) => groupOf(stock) === group).length]));
    const eligibleCounts = Object.fromEntries(GROUPS.map((group) => [
      group,
      stocks.filter((stock) => groupOf(stock) === group && passesPreflight(stock, group)).length,
    ]));
    await patchState("universe", {
      status: "success",
      cycle_date: dataDate,
      total_items: stocks.length,
      processed_count: stocks.length,
      cursor_offset: 0,
      last_success_at: now(),
      next_run_at: new Date(Date.now() + 24 * 60 * 60 * 1_000).toISOString(),
      details: {
        counts,
        eligibleCounts,
        groupDates,
        sources: sourceDiagnostics,
        benchmarks: benchmarksPayload,
        finmindBudget: benchmarkBudget,
        version: VERSION,
      },
    });
    for (const group of GROUPS) {
      const currentCache = await cachedProgress(group);
      const retainedProgress = Math.min(
        eligibleCounts[group],
        currentCache.filter((row: Record<string, any>) =>
          row.analysis_version === ANALYSIS_VERSION && row.status === "ready" &&
          row.data_date === (groupDates[group] || dataDate)).length,
      );
      await patchState(`deep_${group}`, {
        status: "pending",
        cycle_date: groupDates[group] || dataDate,
        cursor_offset: retainedProgress,
        processed_count: retainedProgress,
        total_items: eligibleCounts[group],
        last_error: null,
      });
    }
    return { dataDate, total: stocks.length, counts, eligibleCounts };
  } catch (error) {
    await patchState("universe", { status: "error", last_error: error instanceof Error ? error.message : String(error) });
    throw error;
  }
}

async function syncUniverse() {
  return withLease("universe", syncUniverseUnlocked);
}

function filtersFor(group: Group, date: string) {
  const params = new URLSearchParams({
    select: "*",
    trade_date: `eq.${date}`,
    preliminary_score: "not.is.null",
  });
  if (group === "etf") params.set("instrument_type", "eq.ETF");
  else {
    params.set("instrument_type", "neq.ETF");
    params.set("market", `eq.${group === "otc" ? "上櫃" : "上市"}`);
  }
  return params;
}

async function candidateRefs(group: Group, date: string) {
  const params = filtersFor(group, date);
  params.set("select", "symbol,preliminary_score");
  params.set("order", "preliminary_score.desc.nullslast,symbol.asc");
  params.set("limit", "2000");
  const missingRevenueParams = new URLSearchParams(params);
  missingRevenueParams.set("raw_data->>revenue", "is.null");
  missingRevenueParams.set("limit", "500");
  const [allResult, missingResult] = await Promise.all([
    rest(`stock_snapshots?${params}`),
    group === "etf"
      ? Promise.resolve({ data: [] })
      : rest(`stock_snapshots?${missingRevenueParams}`).catch(() => ({ data: [] })),
  ]);
  const missingSymbols = new Set(
    (Array.isArray(missingResult.data) ? missingResult.data : [])
      .map((row: Record<string, any>) => String(row.symbol)),
  );
  return (Array.isArray(allResult.data) ? allResult.data : []).map((row: Record<string, any>) => ({
    ...row,
    revenueMissing: missingSymbols.has(String(row.symbol)),
  }));
}

async function cachedProgress(group: Group) {
  const params = new URLSearchParams({
    select: "symbol,analysis_version,data_date,status,fetched_at,updated_at,last_attempt_at,last_error,attempt_count,next_retry_at,error_kind,needs_repair,repair_reasons",
    group_name: `eq.${group}`,
    limit: "2000",
  });
  const { data } = await rest(`stock_analysis_cache?${params}`);
  return Array.isArray(data) ? data : [];
}

async function selectedCandidateRows(group: Group, date: string, limit: number) {
  const [refs, cached] = await Promise.all([candidateRefs(group, date), cachedProgress(group)]);
  const current = new Map(
    cached.filter((row: Record<string, any>) =>
      row.analysis_version === ANALYSIS_VERSION && row.data_date === date && row.status === "ready")
      .map((row: Record<string, any>) => [String(row.symbol), row]),
  );
  const failed = new Map(
    cached.filter((row: Record<string, any>) =>
      row.analysis_version === ANALYSIS_VERSION && row.last_error)
      .map((row: Record<string, any>) => [String(row.symbol), row]),
  );
  // Never let one persistently unavailable symbol block the rest of a market.
  // New candidates run first; failed candidates are retried after the unseen
  // backlog, oldest failure first.
  const allMissing = refs.filter((row: Record<string, any>) => !current.has(String(row.symbol)));
  const unseenPool = allMissing.filter((row: Record<string, any>) => !failed.has(String(row.symbol)));
  // The official current-month cross-section can legitimately publish fewer
  // rows than the tradable company universe (for example 2330 was absent while
  // its per-company FinMind filing was already available).  Reserve half of a
  // company batch for these gaps so the backend repairs monthly/quarterly
  // revenue within the same strict API ledger instead of permanently ranking
  // missing companies below already-complete rows.
  const backfillSlots = group === "etf" ? 0 : Math.max(1, Math.ceil(limit / 2));
  const revenueBackfill = unseenPool.filter((row: Record<string, any>) => row.revenueMissing);
  const ordinaryUnseen = unseenPool.filter((row: Record<string, any>) => !row.revenueMissing);
  const priorityWindow: Record<string, any>[] = [];
  for (let index = 0; index < backfillSlots; index += 1) {
    if (revenueBackfill[index]) priorityWindow.push(revenueBackfill[index]);
    if (ordinaryUnseen[index]) priorityWindow.push(ordinaryUnseen[index]);
  }
  const unseen = [
    // Interleave repair and score-ranked candidates.  The quota ledger may
    // shrink a ten-row request to six rows; a block layout would then spend
    // five of six slots on repairs despite the stated 50% policy.
    ...priorityWindow,
    ...ordinaryUnseen.slice(backfillSlots),
    ...revenueBackfill.slice(backfillSlots),
  ];
  const dueFailures = allMissing.filter((row: Record<string, any>) => {
    const failure = failed.get(String(row.symbol));
    return failure && (!failure.next_retry_at || String(failure.next_retry_at) <= now());
  })
    .sort((left: Record<string, any>, right: Record<string, any>) => {
      const leftFailure = failed.get(String(left.symbol));
      const rightFailure = failed.get(String(right.symbol));
      if (Boolean(leftFailure) !== Boolean(rightFailure)) return leftFailure ? 1 : -1;
      if (!leftFailure || !rightFailure) return 0;
      return String(leftFailure.updated_at || "").localeCompare(String(rightFailure.updated_at || ""));
    });
  const currentCandidateCount = refs.length - allMissing.length;
  const dueRepairs = refs.filter((row: Record<string, any>) => {
    const cachedRow = current.get(String(row.symbol));
    if (!cachedRow?.needs_repair) return false;
    if ((cachedRow.repair_reasons || []).some((reason: string) => [
      "v16.3-source-coverage-audit",
      "financial-source-coverage",
      "etf-direction-classification",
    ].includes(reason))) return true;
    const fetchedAt = Date.parse(String(cachedRow.fetched_at || cachedRow.updated_at || ""));
    return !Number.isFinite(fetchedAt) || fetchedAt <= Date.now() - 6 * 60 * 60 * 1_000;
  });
  // Backoff errors are no longer allowed to freeze refreshes of every ready
  // symbol.  Once the unseen backlog is exhausted, retry due failures first
  // and use any remaining slots for the oldest successful analyses.
  const cycleComplete = refs.length > 0 && unseen.length === 0;
  const refreshRows = [...refs]
    .filter((row: Record<string, any>) => {
      const cachedRow = current.get(String(row.symbol));
      if (!cachedRow) return false;
      if (cachedRow.last_error && cachedRow.next_retry_at && String(cachedRow.next_retry_at) > now()) return false;
      const fetchedAt = Date.parse(String(cachedRow.fetched_at || cachedRow.updated_at || ""));
      return !Number.isFinite(fetchedAt) || fetchedAt <= Date.now() - 6 * 60 * 60 * 1_000;
    })
    .sort((left: Record<string, any>, right: Record<string, any>) => {
      const leftAt = current.get(String(left.symbol))?.fetched_at || current.get(String(left.symbol))?.updated_at || "";
      const rightAt = current.get(String(right.symbol))?.fetched_at || current.get(String(right.symbol))?.updated_at || "";
      return leftAt.localeCompare(rightAt) || String(left.symbol).localeCompare(String(right.symbol));
    });
  const repairSlots = Math.min(dueRepairs.length, Math.max(1, Math.floor(limit / 4)));
  const priorityRepairs = dueRepairs.slice(0, repairSlots);
  const primary = unseen.length ? unseen : [...dueFailures, ...refreshRows];
  const prioritized: Record<string, any>[] = [];
  for (let index = 0; index < Math.max(primary.length, priorityRepairs.length); index += 1) {
    if (primary[index]) prioritized.push(primary[index]);
    if (priorityRepairs[index]) prioritized.push(priorityRepairs[index]);
  }
  const chosen = prioritized
    .filter((row: Record<string, any>, index: number, rows: Record<string, any>[]) =>
      rows.findIndex((candidate) => String(candidate.symbol) === String(row.symbol)) === index)
    .slice(0, limit);
  if (!chosen.length) return {
    rows: [],
    total: refs.length,
    currentCount: currentCandidateCount,
    cycleComplete,
    waitingRetry: allMissing.length - unseen.length - dueFailures.length,
    readySymbols: new Set(current.keys()),
    revenueBackfillPending: revenueBackfill.length,
  };
  const symbols = chosen.map((row: Record<string, any>) => String(row.symbol));
  const params = filtersFor(group, date);
  params.set("symbol", `in.(${symbols.join(",")})`);
  params.set("limit", String(symbols.length));
  const { data } = await rest(`stock_snapshots?${params}`);
  const order = new Map(symbols.map((symbol: string, index: number) => [symbol, index]));
  const rows = (Array.isArray(data) ? data : []).sort(
    (left: Record<string, any>, right: Record<string, any>) =>
      (order.get(String(left.symbol)) ?? 999) - (order.get(String(right.symbol)) ?? 999),
  );
  return {
    rows,
    total: refs.length,
    currentCount: currentCandidateCount,
    cycleComplete,
    waitingRetry: allMissing.length - unseen.length - dueFailures.length,
    readySymbols: new Set(current.keys()),
    revenueBackfillPending: revenueBackfill.length,
  };
}

async function persistDeep(stock: Record<string, any>, group: Group, deep: Record<string, any>, result: Record<string, any>) {
  const symbol = String(stock.symbol);
  const updatedAt = now();
  // data_date is the ranking/universe cycle key.  The actual upstream dates
  // remain in analysis.price/sourceDiagnostics; mixing them here caused a
  // one-day FinMind publication lag to be treated as an unfinished cycle.
  const dataDate = stock.trade_date || deep.price?.lastDate || new Date().toISOString().slice(0, 10);
  const priceRows = (deep.priceHistory || []).slice(-280).map((row: Record<string, any>) => ({
    symbol,
    trade_date: row.date,
    open: row.open,
    high: row.high,
    low: row.low,
    close: row.close,
    volume: row.volume,
    trade_value: row.value,
    transactions: finite(row.transactions) ? Math.round(Number(row.transactions)) : null,
    updated_at: updatedAt,
  }));
  const revenueRows = (deep.revenueHistory || []).slice(-40).map((row: Record<string, any>) => ({
    symbol,
    revenue_period: row.period,
    revenue_year: row.year,
    revenue_month: row.month,
    revenue: row.revenue,
    mom: row.mom,
    yoy: row.yoy,
    available_at: row.availableAt || null,
    updated_at: updatedAt,
  }));
  const financialRows = (deep.financial?.history || []).slice(-12).map((row: Record<string, any>) => ({
    symbol,
    report_period: row.period,
    report_date: row.date,
    available_at: row.availableAt || null,
    revenue: row.revenue,
    net_income: row.netIncome,
    eps: row.eps,
    gross_margin: row.grossMargin,
    operating_margin: row.operatingMargin,
    net_margin: row.netMargin,
    roe: row.roe,
    operating_cash_flow: row.operatingCashFlow,
    free_cash_flow: row.freeCashFlow,
    cash_conversion: row.cashConversion,
    inventory: row.inventory,
    receivables: row.receivables,
    debt_ratio: row.debtRatio,
    current_ratio: row.currentRatio,
    interest_coverage: row.interestCoverage,
    non_operating_ratio: row.nonOperatingRatio,
    updated_at: updatedAt,
  }));
  const institutionalRows = (deep.institutional?.history || []).slice(-30).map((row: Record<string, any>) => ({
    symbol,
    trade_date: row.date,
    foreign_net: row.foreign,
    trust_net: row.trust,
    dealer_net: row.dealer,
    institutional_net: row.inst,
    volume_intensity: row.intensity,
    updated_at: updatedAt,
  }));
  const marginRows = (deep.margin?.history || []).slice(-30).map((row: Record<string, any>) => ({
    symbol,
    trade_date: row.date,
    margin_balance: row.marginBalance,
    margin_limit: row.marginLimit,
    short_balance: row.shortBalance,
    updated_at: updatedAt,
  }));
  await Promise.all([
    upsert("stock_price_history", priceRows, "symbol,trade_date"),
    upsert("stock_monthly_revenues", revenueRows, "symbol,revenue_period"),
    upsert("stock_quarterly_financials", financialRows, "symbol,report_period"),
    upsert("stock_institutional_flows", institutionalRows, "symbol,trade_date"),
    upsert("stock_margin_history", marginRows, "symbol,trade_date"),
  ]);
  const deepRevenueIsCurrent = finite(deep.revenue?.revenue) &&
    (!stock.revPeriod || !deep.revenue?.period || deep.revenue.period >= stock.revPeriod);
  const cacheStock = {
    ...stock,
    revenue: deepRevenueIsCurrent ? deep.revenue.revenue : stock.revenue,
    revenueUnit: "TWD",
    rev: deepRevenueIsCurrent ? deep.revenue.yoy : stock.rev,
    revMom: deepRevenueIsCurrent ? deep.revenue.mom : stock.revMom,
    revYtd: deepRevenueIsCurrent ? deep.revenue.ytdYoy : stock.revYtd,
    revAcceleration: deepRevenueIsCurrent ? deep.revenue.acceleration : stock.revAcceleration,
    revPeriod: deepRevenueIsCurrent ? deep.revenue.period : stock.revPeriod,
  };
  // Deep history is authoritative for the candidate itself.  Feed any monthly
  // revenue recovered here back into the daily snapshot so the next universe
  // pass does not keep treating an OpenAPI coverage gap as zero growth.
  if (deep.revenue?.revenue != null) {
    await rest(
      `stock_snapshots?symbol=eq.${encodeURIComponent(symbol)}&trade_date=eq.${encodeURIComponent(stock.trade_date || dataDate)}`,
      {
        method: "PATCH",
        body: {
          revenue_growth: cacheStock.rev ?? null,
          preliminary_score: Number(provisionalScore(cacheStock, group).toFixed(4)),
          raw_data: cacheStock,
          updated_at: updatedAt,
        },
        prefer: "return=minimal",
      },
    );
  }
  const repairReasons = analysisRepairReasons(deep, group);
  await upsert("stock_analysis_cache", [{
    symbol,
    group_name: group,
    data_date: dataDate,
    analysis_version: ANALYSIS_VERSION,
    score: result.score,
    confidence: result.confidence || 0,
    official: Boolean(result.official),
    tier: result.tier,
    stock: compactStock(cacheStock),
    analysis: compactDeep(deep),
    result,
    status: "ready",
    needs_repair: repairReasons.length > 0,
    repair_reasons: repairReasons,
    last_error: null,
    attempt_count: 0,
    next_retry_at: null,
    error_kind: null,
    last_attempt_at: updatedAt,
    fetched_at: deep.fetchedAt || updatedAt,
    updated_at: updatedAt,
  }], "symbol");
  await upsert("opportunity_score_history", [{
    symbol,
    score_date: dataDate,
    model_version: VERSION,
    group_name: group,
    score: result.score,
    confidence: result.confidence || 0,
    official: Boolean(result.official),
    tier: result.tier,
    categories: result.categories || [],
    risk: result.risk || {},
    result,
  }], "symbol,score_date,model_version");
}

async function persistFailure(stock: Record<string, any>, group: Group, error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  const updatedAt = now();
  const { data: previousRows } = await rest(
    `stock_analysis_cache?select=status,analysis,attempt_count&symbol=eq.${encodeURIComponent(String(stock.symbol))}&limit=1`,
  );
  const attemptCount = Math.min(20, Number(previousRows?.[0]?.attempt_count || 0) + 1);
  const statusCode = Number((error as any)?.status) || null;
  const errorKind = statusCode === 402 || statusCode === 429
    ? "rate-limit"
    : statusCode && statusCode >= 500 || (error as any)?.name === "AbortError"
      ? "upstream-temporary"
      : "source-or-network";
  const retryMinutes = errorKind === "rate-limit"
    ? 60
    : Math.min(360, 5 * (2 ** Math.min(6, attemptCount - 1)));
  const previous = Array.isArray(previousRows) ? previousRows[0] : null;
  const retryAt = new Date(Date.now() + retryMinutes * 60 * 1_000).toISOString();
  if (previous?.status === "ready" && previous.analysis) {
    // A transient refresh failure must never destroy the last-known-good row.
    // Keep it visible and attach retry diagnostics separately.
    await rest(`stock_analysis_cache?symbol=eq.${encodeURIComponent(String(stock.symbol))}`, {
      method: "PATCH",
      body: {
        last_error: message.slice(0, 2000),
        attempt_count: attemptCount,
        next_retry_at: retryAt,
        error_kind: errorKind,
        last_attempt_at: updatedAt,
      },
      prefer: "return=minimal",
    });
    return;
  }
  await upsert("stock_analysis_cache", [{
    symbol: String(stock.symbol),
    group_name: group,
    data_date: stock.trade_date || null,
    analysis_version: ANALYSIS_VERSION,
    score: null,
    confidence: 0,
    official: false,
    tier: "深度資料取得失敗，等待下輪重試",
    stock: compactStock(stock),
    analysis: null,
    result: {},
    status: "error",
    last_error: message.slice(0, 2000),
    attempt_count: attemptCount,
    next_retry_at: retryAt,
    error_kind: errorKind,
    last_attempt_at: updatedAt,
    fetched_at: updatedAt,
    updated_at: updatedAt,
  }], "symbol");
}

async function syncDeepUnlocked(group: Group, requestedLimit: number) {
  const jobKey = `deep_${group}`;
  let universe = await getState("universe");
  if (universe?.status === "running" ||
      (universe?.lease_until && Date.parse(String(universe.lease_until)) > Date.now())) {
    return { skipped: true, reason: "universe-refresh-running", group };
  }
  if (!universe?.cycle_date) {
    await syncUniverse();
    universe = await getState("universe");
  }
  const persistedBenchmarks = universe?.details?.benchmarks;
  const benchmarksReady = persistedBenchmarks?.coverage?.listed === true &&
    persistedBenchmarks?.coverage?.otc === true;
  // Each run has a fair request slice.  Reused monthly/quarterly histories
  // cost only four FinMind calls instead of eight, so the same strict request
  // budget can validate twice as many companies after the first cycle.
  const groupLimit = group === "etf"
    ? (FINMIND_AUTHENTICATED ? 23 : 19)
    : (FINMIND_AUTHENTICATED ? 22 : 10);
  const limit = Math.max(1, Math.min(groupLimit, Number(requestedLimit) || groupLimit));
  const date = universe?.details?.groupDates?.[group] || universe?.cycle_date;
  if (!date) throw new Error("Universe date is unavailable");
  const state = await getState(jobKey);
  const selection = await selectedCandidateRows(group, date, limit);
  let rows = selection.rows;
  const { total, currentCount, cycleComplete, waitingRetry = 0, revenueBackfillPending = 0 } = selection;
  const cycleNumber = Number(state?.cycle_number) || 0;
  await patchState(jobKey, {
    status: "running",
    started_at: now(),
    cycle_date: date,
    cursor_offset: currentCount,
    processed_count: currentCount,
    total_items: total,
    cycle_number: cycleNumber,
    last_error: null,
  });
  if (!rows.length) {
    const completionKey = `${date}:${ANALYSIS_VERSION}`;
    const completedNow = currentCount === total && total > 0 && state?.details?.completedCycleKey !== completionKey;
    const rankingFinalization = completedNow
      ? await finalizeRankingCycle(group, date, total)
      : null;
    await patchState(jobKey, {
      status: "success",
      last_success_at: now(),
      cursor_offset: currentCount,
      processed_count: currentCount,
      next_run_at: new Date(Date.now() + 20 * 60 * 1_000).toISOString(),
      cycle_number: cycleNumber + (completedNow ? 1 : 0),
      details: {
        ...(state?.details || {}),
        ...(completedNow ? { completedCycleKey: completionKey, completedCycleAt: now() } : {}),
        ...(completedNow ? { rankingFinalization } : {}),
        message: waitingRetry ? "Waiting for retry backoff" : "No candidates",
        waitingRetry,
        revenueBackfillPending,
        remaining: Math.max(0, total - currentCount),
        version: VERSION,
      },
    });
    return {
      group, date, total, processed: 0, verified: currentCount,
      remaining: Math.max(0, total - currentCount), revenueBackfillPending,
    };
  }
  const symbols = rows.map((row: Record<string, any>) => String(row.symbol));
  const { data: cachedRows } = await rest(
    `stock_analysis_cache?select=symbol,analysis&symbol=in.(${symbols.join(",")})`,
  );
  const cache = new Map((Array.isArray(cachedRows) ? cachedRows : []).map((row: Record<string, any>) => [String(row.symbol), row.analysis]));
  const expectedRevenuePeriod = universe?.details?.sources?.revenue?.period || null;
  const expectedFinancialPeriod = universe?.details?.sources?.financial?.period || null;
  const itemCosts = rows.map((row: Record<string, any>) => {
    if (group === "etf") return 1;
    const stock = row.raw_data || {};
    const analysis = cache.get(String(row.symbol));
    const compatible = analysis?.analysisVersion === ANALYSIS_VERSION;
    const revenuePeriod = expectedRevenuePeriod || stock.revPeriod;
    const financialPeriod = expectedFinancialPeriod || stock.roePeriod;
    const reusableRevenue = compatible && analysis?.revenue?.period &&
      finite(analysis.revenue.revenue) && Number(analysis.revenue.months) > 0 &&
      reusableDiagnostic(analysis, "revenue") &&
      (!revenuePeriod || analysis.revenue.period === revenuePeriod);
    const financialCoverage = analysis?.financial?.sourceCoverage || {};
    const reusableFinancial = compatible && analysis?.financial?.period &&
      Number(analysis.financial.quarters) > 0 &&
      Number(financialCoverage.incomeRows) > 0 && Number(financialCoverage.balanceRows) > 0 &&
      Number(financialCoverage.cashflowRows) > 0 &&
      ["income", "balance", "cashflow"].every((key) => reusableDiagnostic(analysis, key)) &&
      (!financialPeriod || analysis.financial.period === financialPeriod);
    // Price + institutional + margin + lending are always refreshed.  Monthly
    // history adds one request; income/balance/cash-flow add three.
    return 4 + (reusableRevenue ? 0 : 1) + (reusableFinancial ? 0 : 3);
  });
  const claimCap = group === "etf"
    ? (FINMIND_AUTHENTICATED ? 23 : 19)
    // Without a token FinMind allows 300 requests per rolling hour.  A
    // 50-request company slice plus the 19-request ETF slice lets the existing
    // staggered schedule converge on 300 instead of idling around 260; the
    // atomic ledger still trims the final batch so the ceiling is never
    // crossed.  Authenticated projects retain the 88-request fair slice that
    // converges on the documented 600-request ceiling.
    : (FINMIND_AUTHENTICATED ? 88 : 50);
  const finmindBudget = await reserveFinmindBatch(
    itemCosts,
    benchmarksReady ? 0 : 2,
    claimCap,
    { job: jobKey, group, requestedItems: rows.length },
  );
  rows = rows.slice(0, Math.max(0, Number(finmindBudget.items) || 0));
  const revenueBackfillSelected = group === "etf" ? [] : rows
    .filter((row: Record<string, any>) => !finite(row.raw_data?.revenue))
    .map((row: Record<string, any>) => String(row.symbol));
  if (!rows.length) {
    const retryAt = finmindBudget.retryAfterAt || new Date(Date.now() + 20 * 60 * 1_000).toISOString();
    await patchState(jobKey, {
      status: "pending",
      next_run_at: retryAt,
      details: {
        message: "Waiting for FinMind rolling-hour budget",
        waitingRetry,
        revenueBackfillPending,
        remaining: Math.max(0, total - currentCount),
        finmindBudget,
        version: VERSION,
      },
    });
    return {
      group, date, total, processed: 0, verified: currentCount,
      remaining: Math.max(0, total - currentCount), revenueBackfillPending, finmindBudget,
    };
  }
  const successes: string[] = [];
  const failures: { symbol: string; error: string }[] = [];
  const persisted = new Set<string>();
  for (const row of rows) {
    const stock = { ...(row.raw_data || {}), symbol: String(row.symbol), trade_date: row.trade_date };
    try {
      const deep = await buildDeepData(
        stock.symbol,
        row.instrument_type || stock.instrumentType || "股票",
        row.market || stock.market || "上市",
        {
          reuse: cache.get(stock.symbol),
          expectedRevenuePeriod: expectedRevenuePeriod || stock.revPeriod,
          expectedFinancialPeriod: expectedFinancialPeriod || stock.roePeriod,
          expectedTradeDate: stock.trade_date,
          currentQuote: stock,
          bypassCache: true,
          finmindRetries: 0,
          benchmarks: benchmarksReady ? persistedBenchmarks : undefined,
          holdings: row.peer_context?.holdings,
        },
      );
      const result = scoreOpportunity({
        stock,
        deep,
        risk: stock.risk || {},
        context: row.peer_context || {},
      });
      await persistDeep(stock, group, deep, result);
      successes.push(stock.symbol);
      persisted.add(stock.symbol);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      failures.push({ symbol: stock.symbol, error: message });
      try {
        await persistFailure(stock, group, error);
      } catch (persistError) {
        failures.push({
          symbol: stock.symbol,
          error: `無法保存失敗狀態：${persistError instanceof Error ? persistError.message : String(persistError)}`,
        });
      }
    }
  }
  const newlyPersisted = rows.filter((row: Record<string, any>) =>
    persisted.has(String(row.symbol)) && !selection.readySymbols?.has(String(row.symbol))).length;
  const processed = Math.min(total, currentCount + newlyPersisted);
  const completionKey = `${date}:${ANALYSIS_VERSION}`;
  const completedNow = processed === total && total > 0 && state?.details?.completedCycleKey !== completionKey;
  const rankingFinalization = completedNow
    ? await finalizeRankingCycle(group, date, total)
    : null;
  await patchState(jobKey, {
    status: failures.length ? "partial" : "success",
    cursor_offset: processed,
    processed_count: processed,
    cycle_number: cycleNumber + (completedNow ? 1 : 0),
    last_symbol: rows.at(-1)?.symbol || null,
    last_error: failures.length ? failures.map((item) => `${item.symbol}: ${item.error}`).join(" | ").slice(0, 2000) : null,
    last_success_at: successes.length ? now() : state?.last_success_at || null,
    next_run_at: new Date(Date.now() + 20 * 60 * 1_000).toISOString(),
    details: {
      ...(state?.details || {}),
      ...(completedNow ? { completedCycleKey: completionKey, completedCycleAt: now() } : {}),
      ...(completedNow ? { rankingFinalization } : {}),
      successes,
      failures,
      batchSize: rows.length,
      batchLimit: limit,
      finmindQuota: FINMIND_HOURLY_LIMIT,
      finmindBudget,
      verified: processed,
      remaining: Math.max(0, total - processed),
      waitingRetry,
      revenueBackfillPending,
      revenueBackfillSelected,
      refreshCycle: cycleComplete,
      version: VERSION,
    },
  });
  return {
    group,
    date,
    total,
    processed: rows.length,
    verified: processed,
    remaining: Math.max(0, total - processed),
    refreshCycle: cycleComplete,
    successes,
    failures,
    revenueBackfillPending,
    revenueBackfillSelected,
    finmindBudget,
  };
}

async function syncDeep(group: Group, requestedLimit: number) {
  return withLease(`deep_${group}`, () => syncDeepUnlocked(group, requestedLimit));
}

Deno.serve(async (req: Request) => {
  const url = new URL(req.url);
  if (req.method === "GET" && url.searchParams.get("mode") === "history") {
    try {
      return await serveOnDemandHistory(url);
    } catch (error) {
      console.error("[public-history] failed", {
        symbol: url.searchParams.get("symbol") || null,
        error: error instanceof Error ? error.message : String(error),
      });
      return json({
        code: "HISTORY_UPSTREAM_ERROR",
        error: "歷史日線來源暫時無法回應，請稍後重新開啟",
      }, 503);
    }
  }
  if (req.method !== "POST") return json({ error: "Method not allowed" }, 405);
  let adminLogContext: { mode: "universe" | "deep"; group: Group | null } = {
    mode: "deep",
    group: null,
  };
  try {
    if (!await verifyRequest(req)) return json({ error: "Unauthorized" }, 401);
    const body = await req.json().catch(() => ({}));
    const mode = body.mode === "universe" ? "universe" : "deep";
    if (mode === "universe") {
      adminLogContext = { mode, group: null };
      const result = await syncUniverse();
      await logAdminHealth(mode, result);
      return json({ ok: true, version: VERSION, mode, result });
    }
    const group = GROUPS.includes(body.group) ? body.group as Group : "otc";
    adminLogContext = { mode, group };
    const result = await syncDeep(group, body.limit);
    await logAdminHealth(mode, result, group);
    return json({ ok: true, version: VERSION, mode, result });
  } catch (error) {
    console.error("[admin-data-health] sync failed", {
      ...adminLogContext,
      error: error instanceof Error ? error.message : String(error),
      loggedAt: now(),
    });
    return json({ ok: false, version: VERSION, error: error instanceof Error ? error.message : String(error) }, 500);
  }
});
