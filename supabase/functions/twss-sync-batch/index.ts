// Taiwan Stock Smart v16.2 persistent batch updater.
// Called only by pg_cron with a token generated and retained in Supabase Vault.
// @ts-ignore JavaScript modules are shared with the Vercel runtime.
import { ANALYSIS_VERSION, buildDeepData } from "../../../src/deep-data.js";
// @ts-ignore JavaScript modules are shared with the Vercel runtime.
import { handleMarketData } from "../../../src/market-data.js";
// @ts-ignore JavaScript modules are shared with the Vercel runtime.
import { buildPeerContexts, scoreOpportunity } from "../../../src/opportunity-engine.js";

const VERSION = "16.2";
const PROJECT_URL = Deno.env.get("SUPABASE_URL") || "";
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

async function getState(jobKey: string) {
  const { data } = await rest(`stock_sync_state?select=*&job_key=eq.${encodeURIComponent(jobKey)}&limit=1`);
  return Array.isArray(data) ? data[0] : null;
}

async function localPayload(type: string) {
  const url = new URL(`https://sync.internal/api/market-data?type=${type}&refresh=1`);
  const response = await handleMarketData(new Request(url), url);
  const payload = await response.json();
  if (!response.ok) throw new Error(`${type}: ${payload.error || response.status}`);
  return payload;
}

function groupOf(stock: Record<string, any>): Group {
  if (stock.instrumentType === "ETF" || /^00\d{2,4}$/.test(String(stock.symbol || ""))) return "etf";
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

function compactStock(stock: Record<string, any>) {
  const keys = [
    "symbol", "name", "market", "instrumentType", "industry", "close", "change", "open", "high", "low",
    "volume", "value", "transactions", "pe", "pb", "yield", "rev", "revMom", "revYtd", "revAcceleration",
    "revPeriod", "roe", "roePeriod", "eps", "grossMargin", "operatingMargin", "netMargin", "debt",
    "foreign", "trust", "dealer", "inst", "marginBalance", "marginChange", "shortBalance", "shortChange", "risk",
  ];
  return Object.fromEntries(keys.map((key) => [key, stock[key]]).filter(([, value]) => value !== undefined));
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

async function syncUniverse() {
  await patchState("universe", { status: "running", started_at: now(), last_error: null });
  try {
    const [stocksPayload, revenuePayload, financialPayload] = await Promise.all([
      localPayload("stocks"),
      localPayload("revenue"),
      localPayload("financials"),
    ]);
    const merged = new Map<string, Record<string, any>>(
      (stocksPayload.stocks || []).map((stock: Record<string, any>) => [String(stock.symbol), { ...stock }]),
    );
    for (const row of [...(revenuePayload.fundamentals || []), ...(financialPayload.fundamentals || [])]) {
      const current = merged.get(String(row.symbol));
      if (current) Object.assign(current, row);
    }
    const stocks = [...merged.values()];
    if (stocks.length < 100) throw new Error(`Universe coverage too low: ${stocks.length}`);
    const contexts = buildPeerContexts(stocks);
    const dataDate = stocksPayload.date || new Date().toISOString().slice(0, 10);
    const updatedAt = now();
    const masters = stocks.map((stock) => ({
      symbol: String(stock.symbol),
      name: stock.name || String(stock.symbol),
      market: stock.market || "上市",
      industry: stock.industry || "未分類",
      security_type: groupOf(stock) === "etf" ? "ETF" : "股票",
      source: stock.market === "上櫃" ? "TPEx" : "TWSE",
      active: true,
      last_trade_date: dataDate,
      metadata: { instrumentType: stock.instrumentType || (groupOf(stock) === "etf" ? "ETF" : "股票") },
      updated_at: updatedAt,
    }));
    await upsert("stock_master", masters, "symbol");
    const snapshots = stocks.map((stock) => {
      const group = groupOf(stock);
      return {
        symbol: String(stock.symbol),
        trade_date: dataDate,
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
        preliminary_score: stock.hardExcluded ? null : Number(provisionalScore(stock, group).toFixed(4)),
        peer_context: contexts[String(stock.symbol)] || {},
        raw_data: stock,
        source_dates: stocksPayload.dates || {},
        source: stock.market === "上櫃" ? "TPEx/TWSE/FinMind" : "TWSE/FinMind",
        updated_at: updatedAt,
      };
    });
    await upsert("stock_snapshots", snapshots, "symbol,trade_date", 150);
    const counts = Object.fromEntries(GROUPS.map((group) => [group, stocks.filter((stock) => groupOf(stock) === group).length]));
    await patchState("universe", {
      status: "success",
      cycle_date: dataDate,
      total_items: stocks.length,
      processed_count: stocks.length,
      cursor_offset: 0,
      last_success_at: now(),
      details: { counts, sourceDates: stocksPayload.dates || {}, version: VERSION },
    });
    for (const group of GROUPS) {
      const existing = await getState(`deep_${group}`);
      const retainedProgress = Math.min(counts[group], Number(existing?.processed_count) || 0);
      await patchState(`deep_${group}`, {
        status: "pending",
        cycle_date: dataDate,
        cursor_offset: retainedProgress,
        processed_count: retainedProgress,
        total_items: counts[group],
        last_error: null,
      });
    }
    return { dataDate, total: stocks.length, counts };
  } catch (error) {
    await patchState("universe", { status: "error", last_error: error instanceof Error ? error.message : String(error) });
    throw error;
  }
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
  const { data } = await rest(`stock_snapshots?${params}`);
  return Array.isArray(data) ? data : [];
}

async function cachedProgress(group: Group) {
  const params = new URLSearchParams({
    select: "symbol,analysis_version,status,fetched_at,updated_at",
    group_name: `eq.${group}`,
    limit: "2000",
  });
  const { data } = await rest(`stock_analysis_cache?${params}`);
  return Array.isArray(data) ? data : [];
}

async function selectedCandidateRows(group: Group, date: string, limit: number) {
  const [refs, cached] = await Promise.all([candidateRefs(group, date), cachedProgress(group)]);
  const current = new Map(
    cached.filter((row: Record<string, any>) => row.analysis_version === ANALYSIS_VERSION)
      .map((row: Record<string, any>) => [String(row.symbol), row]),
  );
  const missing = refs.filter((row: Record<string, any>) => !current.has(String(row.symbol)));
  const currentCandidateCount = refs.length - missing.length;
  const cycleComplete = refs.length > 0 && missing.length === 0;
  const chosen = (cycleComplete
    ? [...refs].sort((left: Record<string, any>, right: Record<string, any>) => {
      const leftAt = current.get(String(left.symbol))?.fetched_at || current.get(String(left.symbol))?.updated_at || "";
      const rightAt = current.get(String(right.symbol))?.fetched_at || current.get(String(right.symbol))?.updated_at || "";
      return leftAt.localeCompare(rightAt) || String(left.symbol).localeCompare(String(right.symbol));
    })
    : missing
  ).slice(0, limit);
  if (!chosen.length) return { rows: [], total: refs.length, currentCount: currentCandidateCount, cycleComplete };
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
  return { rows, total: refs.length, currentCount: currentCandidateCount, cycleComplete };
}

async function persistDeep(stock: Record<string, any>, group: Group, deep: Record<string, any>, result: Record<string, any>) {
  const symbol = String(stock.symbol);
  const updatedAt = now();
  const dataDate = deep.price?.lastDate || stock.trade_date || new Date().toISOString().slice(0, 10);
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
  await upsert("stock_analysis_cache", [{
    symbol,
    group_name: group,
    data_date: dataDate,
    analysis_version: ANALYSIS_VERSION,
    score: result.score,
    confidence: result.confidence || 0,
    official: Boolean(result.official),
    tier: result.tier,
    stock: compactStock(stock),
    analysis: compactDeep(deep),
    result,
    status: "ready",
    last_error: null,
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
    fetched_at: updatedAt,
    updated_at: updatedAt,
  }], "symbol");
}

async function syncDeep(group: Group, requestedLimit: number) {
  const jobKey = `deep_${group}`;
  const limit = Math.max(1, Math.min(3, Number(requestedLimit) || 2));
  let universe = await getState("universe");
  if (!universe?.cycle_date) {
    await syncUniverse();
    universe = await getState("universe");
  }
  const date = universe?.cycle_date;
  if (!date) throw new Error("Universe date is unavailable");
  const state = await getState(jobKey);
  const selection = await selectedCandidateRows(group, date, limit);
  const { rows, total, currentCount, cycleComplete } = selection;
  const completedFirstCycle = cycleComplete && Number(state?.processed_count || 0) < total;
  const cycleNumber = (Number(state?.cycle_number) || 0) + (completedFirstCycle ? 1 : 0);
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
    await patchState(jobKey, {
      status: "success",
      last_success_at: now(),
      cursor_offset: currentCount,
      processed_count: currentCount,
      details: { message: "No candidates", remaining: Math.max(0, total - currentCount), version: VERSION },
    });
    return { group, date, total, processed: 0, verified: currentCount, remaining: Math.max(0, total - currentCount) };
  }
  const symbols = rows.map((row: Record<string, any>) => String(row.symbol));
  const { data: cachedRows } = await rest(
    `stock_analysis_cache?select=symbol,analysis&symbol=in.(${symbols.join(",")})`,
  );
  const cache = new Map((Array.isArray(cachedRows) ? cachedRows : []).map((row: Record<string, any>) => [String(row.symbol), row.analysis]));
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
          expectedRevenuePeriod: stock.revPeriod || null,
          expectedFinancialPeriod: stock.roePeriod || null,
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
        persisted.add(stock.symbol);
      } catch (persistError) {
        failures.push({
          symbol: stock.symbol,
          error: `無法保存失敗狀態：${persistError instanceof Error ? persistError.message : String(persistError)}`,
        });
      }
    }
  }
  const newlyPersisted = cycleComplete
    ? 0
    : rows.filter((row: Record<string, any>) => persisted.has(String(row.symbol))).length;
  const processed = Math.min(total, currentCount + newlyPersisted);
  await patchState(jobKey, {
    status: failures.length ? "partial" : "success",
    cursor_offset: processed,
    processed_count: processed,
    last_symbol: rows.at(-1)?.symbol || null,
    last_error: failures.length ? failures.map((item) => `${item.symbol}: ${item.error}`).join(" | ").slice(0, 2000) : null,
    last_success_at: successes.length ? now() : state?.last_success_at || null,
    details: {
      successes,
      failures,
      batchSize: rows.length,
      verified: processed,
      remaining: Math.max(0, total - processed),
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
  };
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return json({ error: "Method not allowed" }, 405);
  try {
    if (!await verifyRequest(req)) return json({ error: "Unauthorized" }, 401);
    const body = await req.json().catch(() => ({}));
    const mode = body.mode === "universe" ? "universe" : "deep";
    if (mode === "universe") return json({ ok: true, version: VERSION, mode, result: await syncUniverse() });
    const group = GROUPS.includes(body.group) ? body.group as Group : "otc";
    return json({ ok: true, version: VERSION, mode, result: await syncDeep(group, body.limit) });
  } catch (error) {
    return json({ ok: false, version: VERSION, error: error instanceof Error ? error.message : String(error) }, 500);
  }
});
