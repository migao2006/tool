const DEFAULT_URL = "https://lfkdkdyaatdlizryiyon.supabase.co";
const DEFAULT_PUBLIC_KEY = "sb_publishable_r3h9eQIYdIqScvmc77avAg_OLgBT6lh";

const env = globalThis.process?.env || {};
const SUPABASE_URL = env.SUPABASE_URL || DEFAULT_URL;
const SUPABASE_PUBLIC_KEY =
  env.SUPABASE_PUBLISHABLE_KEY || env.SUPABASE_ANON_KEY || DEFAULT_PUBLIC_KEY;

const finite = (value) => value != null && Number.isFinite(Number(value));

async function request(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeout || 20_000);
  try {
    const response = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
      method: options.method || "GET",
      headers: {
        accept: "application/json",
        apikey: SUPABASE_PUBLIC_KEY,
        ...(options.headers || {}),
      },
      signal: controller.signal,
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`後端資料庫 HTTP ${response.status}`);
    if (options.method === "HEAD") return { response, data: null };
    return { response, data: await response.json() };
  } finally {
    clearTimeout(timer);
  }
}

async function countRows(table, filters = "") {
  const { response } = await request(
    `${table}?select=symbol${filters ? `&${filters}` : ""}`,
    { method: "HEAD", headers: { Prefer: "count=exact" } },
  );
  const range = response.headers.get("content-range") || "";
  const count = Number(range.split("/").at(-1));
  return Number.isFinite(count) ? count : 0;
}

function normalizeStoredRow(row) {
  return {
    stock: row.stock || {},
    analysis: row.analysis || null,
    result: row.result || {
      score: finite(row.score) ? Number(row.score) : null,
      confidence: finite(row.confidence) ? Number(row.confidence) : 0,
      official: Boolean(row.official),
      tier: row.tier || "後端深度資料",
    },
  };
}

export async function readBackendRankings(limit = 100) {
  const safeLimit = Math.max(10, Math.min(200, Number(limit) || 100));
  const select = encodeURIComponent(
    "symbol,group_name,data_date,score,confidence,official,tier,stock,analysis,result,updated_at",
  );
  const groups = ["listed", "otc", "etf"];
  const [rowsByGroup, counts, stateResult] = await Promise.all([
    Promise.all(groups.map(async (group) => {
      const path = `stock_analysis_cache?select=${select}&group_name=eq.${group}&status=eq.ready&order=score.desc.nullslast,confidence.desc&limit=${safeLimit}`;
      const { data } = await request(path);
      return [group, Array.isArray(data) ? data : []];
    })),
    Promise.all(groups.map((group) => countRows("stock_analysis_cache", `group_name=eq.${group}&status=eq.ready`))),
    request("stock_sync_state?select=*&order=job_key.asc").catch(() => ({ data: [] })),
  ]);
  const rawGroups = Object.fromEntries(rowsByGroup);
  const dates = Object.values(rawGroups).flat().map((row) => row.data_date).filter(Boolean).sort();
  const updated = Object.values(rawGroups).flat().map((row) => row.updated_at).filter(Boolean).sort();
  return {
    mode: counts.some(Boolean) ? "live" : "empty",
    version: "16.2",
    methodology: "persistent-batched-opportunity-engine-v16.2",
    generatedAt: updated.at(-1) || null,
    dataDate: dates.at(-1) || null,
    groups: Object.fromEntries(groups.map((group) => [group, rawGroups[group].map(normalizeStoredRow)])),
    universe: {
      verifiedCandidates: Object.fromEntries(groups.map((group, index) => [group, counts[index]])),
    },
    backend: {
      persistent: true,
      counts: Object.fromEntries(groups.map((group, index) => [group, counts[index]])),
      sync: stateResult.data || [],
    },
  };
}

export async function readBackendHistory(symbol, limit = 280) {
  if (!/^\d{4,6}$/.test(String(symbol || ""))) throw new Error("股票代號格式不正確");
  const safeLimit = Math.max(60, Math.min(300, Number(limit) || 280));
  const select = encodeURIComponent(
    "trade_date,open,high,low,close,volume,trade_value,transactions",
  );
  const { data } = await request(
    `stock_price_history?select=${select}&symbol=eq.${encodeURIComponent(symbol)}&order=trade_date.desc&limit=${safeLimit}`,
  );
  const history = (Array.isArray(data) ? data : []).reverse().map((row) => ({
    date: row.trade_date,
    open: finite(row.open) ? Number(row.open) : null,
    high: finite(row.high) ? Number(row.high) : null,
    low: finite(row.low) ? Number(row.low) : null,
    close: finite(row.close) ? Number(row.close) : null,
    volume: finite(row.volume) ? Number(row.volume) : null,
    value: finite(row.trade_value) ? Number(row.trade_value) : null,
    transactions: finite(row.transactions) ? Number(row.transactions) : null,
  })).filter((row) => row.close != null && row.high != null && row.low != null);
  return {
    mode: history.length >= 60 ? "live" : history.length ? "partial" : "empty",
    symbol: String(symbol),
    source: "Supabase 後端歷史資料庫",
    count: history.length,
    period: history.at(-1)?.date || null,
    history,
  };
}

export async function readBackendStatus() {
  const { data } = await request("stock_sync_state?select=*&order=job_key.asc");
  return {
    mode: "live",
    version: "16.2",
    persistent: true,
    jobs: Array.isArray(data) ? data : [],
  };
}

export const backendStoreInternals = { request, countRows, normalizeStoredRow };
