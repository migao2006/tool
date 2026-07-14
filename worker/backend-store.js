const DEFAULT_URL = "https://lfkdkdyaatdlizryiyon.supabase.co";
const DEFAULT_PUBLIC_KEY = "sb_publishable_r3h9eQIYdIqScvmc77avAg_OLgBT6lh";

const env = globalThis.process?.env || {};
const SUPABASE_URL = env.SUPABASE_URL || DEFAULT_URL;
const SUPABASE_PUBLIC_KEY =
  env.SUPABASE_PUBLISHABLE_KEY || env.SUPABASE_ANON_KEY || DEFAULT_PUBLIC_KEY;
const EXPECTED_ANALYSIS_VERSION = "16.3-ultimate-data-audit";

const finite = (value) => value != null && Number.isFinite(Number(value));

const pick = (value, keys) => Object.fromEntries(
  keys.filter((key) => value?.[key] !== undefined).map((key) => [key, value[key]]),
);

function compactRankingStock(stock = {}) {
  return pick(stock, [
    "symbol", "name", "market", "instrumentType", "industry", "close", "change",
    "revenue", "revPeriod", "quarterRevenue", "quarterRevenuePeriod",
  ]);
}

function compactRankingAnalysis(analysis) {
  if (!analysis) return null;
  const diagnostics = Object.fromEntries(Object.entries(analysis.sourceDiagnostics || {}).map(([key, value]) => [
    key,
    pick(value, ["status", "statusCode", "actualPeriod", "expectedPeriod"]),
  ]));
  return {
    analysisVersion: analysis.analysisVersion,
    revenue: pick(analysis.revenue, [
      "revenue", "period", "avg3Yoy", "acceleration3", "consecutiveAcceleration",
      "availableAt", "postRelease5", "postReleaseStatus", "postReleaseObservedDays", "yoyStatus",
    ]),
    financial: pick(analysis.financial, [
      "revenue", "period", "revenueStatus", "operatingMargin", "operatingMarginYoyChange",
      "cashConversion", "ttmOperatingCashFlow", "cashConversionBasis",
    ]),
    institutional: pick(analysis.institutional, ["inst20", "intensity5"]),
    price: pick(analysis.price, ["relative20", "return20", "volumeRatio", "atrPct"]),
    margin: pick(analysis.margin, [
      "applicable", "marginEligible", "financingEligible", "note", "sourceNote", "marginBalance", "marginUsage",
    ]),
    etf: pick(analysis.etf, [
      "benchmark", "premiumDiscount", "navUpdatedAt", "leveraged", "inverse", "fundType",
    ]),
    sourceDiagnostics: diagnostics,
  };
}

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

function normalizeStoredRow(row, currentDataDate = null) {
  const storedResult = row.result || {
    score: finite(row.score) ? Number(row.score) : null,
    confidence: finite(row.confidence) ? Number(row.confidence) : 0,
    official: Boolean(row.official),
    tier: row.tier || "後端深度資料",
  };
  return {
    dataDate: row.data_date || null,
    updatedAt: row.updated_at || null,
    isStale: Boolean(currentDataDate && row.data_date && row.data_date !== currentDataDate),
    stock: compactRankingStock(row.stock || {}),
    analysis: compactRankingAnalysis(row.analysis),
    // Ranking cards only render the aggregate category values.  The complete
    // factor-level evidence remains available from readBackendAnalysis(), so
    // do not make every mobile ranking download the same verbose item arrays.
    result: {
      ...pick(storedResult, [
        "symbol", "name", "group", "score", "baseScore", "confidence", "historyCoverage",
        "official", "freshnessVerified", "tier", "archetypes", "reasons", "risk", "missing",
      ]),
      ...(Array.isArray(storedResult.categories) ? {
        categories: storedResult.categories.map((category) => ({
          key: category.key,
          label: category.label,
          score: category.score,
          weight: category.weight,
          coverage: category.coverage,
        })),
      } : {}),
    },
  };
}

function compactSyncState(row) {
  if (!row || typeof row !== "object") return row;
  // Universe benchmarks contain hundreds of daily points and are already
  // served by the dedicated benchmarks endpoint.  Sync/status consumers only
  // need their coverage summary, not a second copy of the full time series.
  const { benchmarks: _benchmarkSeries, ...details } = row.details || {};
  return { ...row, details };
}

export async function readBackendRankings(limit = 100) {
  const safeLimit = Math.max(1, Math.min(200, Number(limit) || 100));
  const select = encodeURIComponent(
    "symbol,group_name,data_date,score,confidence,official,tier,stock,analysis,result,updated_at",
  );
  const groups = ["listed", "otc", "etf"];
  const stateResult = await request(
    "stock_sync_state?select=*&job_key=in.(universe,deep_listed,deep_otc,deep_etf)&order=job_key.asc",
  ).catch(() => ({ data: [] }));
  const states = Array.isArray(stateResult.data) ? stateResult.data : [];
  const universeState = states.find((row) => row.job_key === "universe");
  const groupDates = Object.fromEntries(groups.map((group) => [
    group,
    universeState?.details?.groupDates?.[group] || universeState?.cycle_date || null,
  ]));
  const filters = (group) => [
    `group_name=eq.${group}`,
    "status=eq.ready",
    `analysis_version=eq.${encodeURIComponent(EXPECTED_ANALYSIS_VERSION)}`,
  ].filter(Boolean).join("&");
  const [rowsByGroup, counts] = await Promise.all([
    Promise.all(groups.map(async (group) => {
      const path = `stock_analysis_cache?select=${select}&${filters(group)}&order=score.desc.nullslast,confidence.desc&limit=${safeLimit}`;
      const { data } = await request(path);
      return [group, Array.isArray(data) ? data : []];
    })),
    Promise.all(groups.map((group) => countRows("stock_analysis_cache", filters(group)))),
  ]);
  const rawGroups = Object.fromEntries(rowsByGroup);
  const dates = Object.values(rawGroups).flat().map((row) => row.data_date).filter(Boolean).sort();
  const updated = Object.values(rawGroups).flat().map((row) => row.updated_at).filter(Boolean).sort();
  return {
    mode: counts.some(Boolean) ? "live" : "empty",
    version: "16.3",
    methodology: "persistent-batched-opportunity-engine-v16.3",
    generatedAt: updated.at(-1) || null,
    dataDate: Object.values(groupDates).filter(Boolean).sort().at(-1) || dates.at(-1) || null,
    groupDates,
    groups: Object.fromEntries(groups.map((group) => [
      group,
      rawGroups[group].map((row) => normalizeStoredRow(row, groupDates[group])),
    ])),
    universe: {
      verifiedCandidates: Object.fromEntries(groups.map((group, index) => [group, counts[index]])),
    },
    backend: {
      persistent: true,
      counts: Object.fromEntries(groups.map((group, index) => [group, counts[index]])),
      sync: states.map(compactSyncState),
    },
  };
}

export async function readBackendHistory(symbol, limit = 280) {
  if (!/^\d{4,6}[A-Z]?$/i.test(String(symbol || ""))) throw new Error("股票代號格式不正確");
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

export async function readBackendAnalysis(symbol) {
  if (!/^\d{4,6}[A-Z]?$/i.test(String(symbol || ""))) throw new Error("股票代號格式不正確");
  const select = encodeURIComponent(
    "symbol,group_name,data_date,stock,analysis,result,analysis_version,status,last_error,fetched_at,updated_at",
  );
  const { data } = await request(
    `stock_analysis_cache?select=${select}&symbol=eq.${encodeURIComponent(symbol)}&status=eq.ready&analysis_version=eq.${encodeURIComponent(EXPECTED_ANALYSIS_VERSION)}&limit=1`,
  );
  const row = Array.isArray(data) ? data[0] : null;
  if (!row?.analysis) throw new Error(`${symbol} 尚未完成後端深度驗證`);
  return {
    mode: "live",
    symbol: String(symbol),
    dataDate: row.data_date || null,
    fetchedAt: row.fetched_at || row.updated_at || null,
    stock: row.stock || {},
    result: row.result || {},
    ...row.analysis,
  };
}

export async function readAiResearch(symbol) {
  if (!/^\d{4,6}[A-Z]?$/i.test(String(symbol || ""))) throw new Error("股票代號格式不正確");
  const select = encodeURIComponent(
    "id,symbol,group_name,data_date,provider,model,schema_version,selected_reason,verdict,ai_confidence,analysis,generated_at,expires_at",
  );
  const { data } = await request(
    `ai_stock_research?select=${select}&symbol=eq.${encodeURIComponent(symbol)}&order=generated_at.desc&limit=1`,
  );
  const row = Array.isArray(data) ? data[0] : null;
  if (!row?.analysis) {
    return {
      available: false,
      symbol: String(symbol),
      reason: "not-selected-or-not-generated",
    };
  }
  const expiresAt = row.expires_at ? Date.parse(row.expires_at) : Number.NaN;
  if (Number.isFinite(expiresAt) && expiresAt <= Date.now()) {
    return {
      available: false,
      symbol: String(symbol),
      reason: "expired",
    };
  }
  return {
    available: true,
    symbol: String(row.symbol),
    group: row.group_name,
    dataDate: row.data_date || null,
    provider: row.provider,
    model: row.model,
    schemaVersion: row.schema_version,
    selectedReason: row.selected_reason,
    verdict: row.verdict,
    aiConfidence: finite(row.ai_confidence) ? Number(row.ai_confidence) : null,
    analysis: row.analysis,
    generatedAt: row.generated_at || null,
    expiresAt: row.expires_at || null,
  };
}

export async function readBackendStatus() {
  const { data } = await request(
    "stock_sync_state?select=*&job_key=in.(universe,deep_listed,deep_otc,deep_etf)&order=job_key.asc",
  );
  return {
    mode: "live",
    version: "16.3",
    persistent: true,
    jobs: Array.isArray(data) ? data.map(compactSyncState) : [],
  };
}

export const backendStoreInternals = {
  request,
  countRows,
  normalizeStoredRow,
  compactSyncState,
  compactRankingStock,
  compactRankingAnalysis,
};
