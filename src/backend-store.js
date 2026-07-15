const DEFAULT_URL = "https://lfkdkdyaatdlizryiyon.supabase.co";
const DEFAULT_PUBLIC_KEY = "sb_publishable_r3h9eQIYdIqScvmc77avAg_OLgBT6lh";

const env = globalThis.process?.env || {};
const SUPABASE_URL = env.SUPABASE_URL || DEFAULT_URL;
const SUPABASE_PUBLIC_KEY =
  env.SUPABASE_PUBLISHABLE_KEY || env.SUPABASE_ANON_KEY || DEFAULT_PUBLIC_KEY;
const EXPECTED_ANALYSIS_VERSION = "16.3-ultimate-data-audit";
const SCORE_MODEL_VERSION = "16.3";
const PUBLIC_API_VERSION = "17.1";

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

function safeErrorCode(value) {
  if (value == null || String(value).trim() === "") return null;
  const message = String(value).toLowerCase();
  if (/(^|\D)429(\D|$)|rate.?limit|quota|too many requests/.test(message)) return "rate_limited";
  if (/(^|\D)(408|504)(\D|$)|timeout|timed out|abort/.test(message)) return "upstream_timeout";
  if (/(^|\D)(401|403)(\D|$)|unauthori[sz]ed|forbidden|credential|api.?key/.test(message)) {
    return "upstream_authentication_failed";
  }
  if (/(^|\D)404(\D|$)|not found/.test(message)) return "upstream_not_found";
  if (/(^|\D)(500|502|503)(\D|$)|network|fetch|econn|socket|dns/.test(message)) {
    return "upstream_unavailable";
  }
  if (/(^|\D)(400|409|422)(\D|$)|invalid|validation/.test(message)) return "invalid_upstream_response";
  return "sync_error";
}

function compactRankingFinalization(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const compact = pick(value, ["status", "attemptedAt"]);
  if (value.result && typeof value.result === "object") {
    compact.result = pick(value.result, [
      "group", "scoreDate", "modelVersion", "expected", "scored", "official", "status",
    ]);
  }
  if (value.backtest && typeof value.backtest === "object") {
    compact.backtest = pick(value.backtest, [
      "status", "group", "modelVersion", "rowsAffected", "evaluatedAt",
    ]);
    const backtestErrorCode = safeErrorCode(value.backtest.error || value.backtest.message);
    if (backtestErrorCode) compact.backtest.errorCode = backtestErrorCode;
  }
  const errorCode = safeErrorCode(value.error || value.message);
  if (errorCode) compact.errorCode = errorCode;
  return compact;
}

function failureSummary(failures) {
  if (!Array.isArray(failures) || !failures.length) return undefined;
  const byCode = failures.reduce((counts, failure) => {
    const code = safeErrorCode(failure?.error || failure?.message || failure) || "sync_error";
    counts[code] = (counts[code] || 0) + 1;
    return counts;
  }, {});
  return { count: failures.length, byCode };
}

function compactSyncState(row) {
  if (!row || typeof row !== "object") return row;
  // This object is returned by public endpoints.  Keep only operational
  // progress fields and stable codes: service URLs, lease tokens, raw upstream
  // errors and per-symbol exception messages must remain server-side.
  const compact = pick(row, [
    "job_key", "group_name", "cycle_date", "cursor_offset", "total_items",
    "processed_count", "cycle_number", "status", "started_at", "last_success_at",
    "next_run_at", "updated_at",
  ]);
  const lastErrorCode = safeErrorCode(row.last_error);
  if (lastErrorCode) compact.last_error_code = lastErrorCode;

  const source = row.details && typeof row.details === "object" && !Array.isArray(row.details)
    ? row.details
    : {};
  const details = pick(source, [
    "counts", "eligibleCounts", "groupDates", "remaining", "waitingRetry",
    "revenueBackfillPending", "verified", "batchSize", "batchLimit", "finmindQuota",
    "refreshCycle", "completedCycleKey", "completedCycleAt", "version",
  ]);
  const failures = failureSummary(source.failures);
  if (failures) details.failureSummary = failures;
  const rankingFinalization = compactRankingFinalization(source.rankingFinalization);
  if (rankingFinalization) details.rankingFinalization = rankingFinalization;
  compact.details = details;
  return compact;
}

function rpcObject(data, fallback = {}) {
  if (data && typeof data === "object" && !Array.isArray(data)) return data;
  if (Array.isArray(data) && data[0] && typeof data[0] === "object") return data[0];
  return fallback;
}

async function readFinalCycles(group) {
  const select = encodeURIComponent(
    "group_name,score_date,model_version,status,expected_count,scored_count,official_count,finalized_at",
  );
  const { data } = await request(
    `opportunity_ranking_cycles?select=${select}&group_name=eq.${group}` +
    `&model_version=eq.${encodeURIComponent(SCORE_MODEL_VERSION)}` +
    "&status=eq.final&order=score_date.desc&limit=2",
  );
  return Array.isArray(data) ? data : [];
}

async function readOfficialScores(group, cycles) {
  const select = encodeURIComponent("symbol,score_date,score,confidence,official");
  const rows = await Promise.all(cycles.map(async (cycle) => {
    const { data } = await request(
      `opportunity_score_history?select=${select}&group_name=eq.${group}` +
      `&model_version=eq.${encodeURIComponent(SCORE_MODEL_VERSION)}` +
      `&score_date=eq.${encodeURIComponent(cycle.score_date)}` +
      "&official=eq.true&order=score.desc.nullslast,confidence.desc.nullslast,symbol.asc&limit=2000",
    );
    return Array.isArray(data) ? data : [];
  }));
  return rows.flat();
}

function rankedScores(rows, date) {
  const sorted = rows
    .filter((row) => row.score_date === date && finite(row.score))
    .sort((left, right) =>
      Number(right.score) - Number(left.score) ||
      Number(right.confidence || 0) - Number(left.confidence || 0) ||
      String(left.symbol).localeCompare(String(right.symbol)));
  const result = new Map();
  let previous = null;
  let rank = 0;
  sorted.forEach((row, index) => {
    const key = `${Number(row.score)}:${Number(row.confidence || 0)}`;
    if (key !== previous) rank = index + 1;
    previous = key;
    result.set(String(row.symbol), {
      rank,
      score: Number(row.score),
      confidence: finite(row.confidence) ? Number(row.confidence) : null,
    });
  });
  return result;
}

function rankingTrend(symbol, cycles, scoreRows, precomputed = null) {
  const dates = cycles.map((cycle) => cycle.score_date).filter(Boolean);
  const status = dates.length >= 2 ? "ready" : "accumulating";
  const ranks = precomputed || new Map(
    dates.map((date) => [date, rankedScores(scoreRows, date)]),
  );
  const current = dates[0] ? ranks.get(dates[0])?.get(String(symbol)) : null;
  const previous = dates[1] ? ranks.get(dates[1])?.get(String(symbol)) : null;
  return {
    status,
    finalDateCount: dates.length,
    minimumFinalDates: 2,
    currentDate: dates[0] || null,
    previousDate: dates[1] || null,
    rank: current?.rank ?? null,
    previousRank: previous?.rank ?? null,
    rankDelta: status === "ready" && current && previous
      ? previous.rank - current.rank
      : null,
    scoreDelta: status === "ready" && current && previous
      ? Number((current.score - previous.score).toFixed(4))
      : null,
  };
}

function rankingTrendForStoredRow(row, cycles, scoreRows, precomputed = null) {
  const trend = rankingTrend(row.symbol, cycles, scoreRows, precomputed);
  if (trend.currentDate && row.data_date !== trend.currentDate) {
    return {
      ...trend,
      status: "date_mismatch",
      cacheDataDate: row.data_date || null,
      rank: null,
      previousRank: null,
      rankDelta: null,
      scoreDelta: null,
    };
  }
  return trend;
}

export async function readBackendRankings(limit = 100) {
  const safeLimit = Math.max(1, Math.min(200, Number(limit) || 100));
  const select = encodeURIComponent(
    "symbol,group_name,data_date,score,confidence,official,tier,stock,analysis,result,updated_at",
  );
  const groups = ["listed", "otc", "etf"];
  const [stateResult, cycleEntries] = await Promise.all([
    request(
      "stock_sync_state?select=*&job_key=in.(universe,deep_listed,deep_otc,deep_etf)&order=job_key.asc",
    ).catch(() => ({ data: [] })),
    Promise.all(groups.map(async (group) => [group, await readFinalCycles(group)])),
  ]);
  const states = Array.isArray(stateResult.data) ? stateResult.data : [];
  const cyclesByGroup = Object.fromEntries(cycleEntries);
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
  const [rowsByGroup, counts, scoreEntries] = await Promise.all([
    Promise.all(groups.map(async (group) => {
      const path = `stock_analysis_cache?select=${select}&${filters(group)}&order=score.desc.nullslast,confidence.desc&limit=${safeLimit}`;
      const { data } = await request(path);
      return [group, Array.isArray(data) ? data : []];
    })),
    Promise.all(groups.map((group) => countRows("stock_analysis_cache", filters(group)))),
    Promise.all(groups.map(async (group) => [
      group,
      await readOfficialScores(group, cyclesByGroup[group]),
    ])),
  ]);
  const rawGroups = Object.fromEntries(rowsByGroup);
  const scoresByGroup = Object.fromEntries(scoreEntries);
  const scoreRanksByGroup = Object.fromEntries(groups.map((group) => [
    group,
    new Map(cyclesByGroup[group].map((cycle) => [
      cycle.score_date,
      rankedScores(scoresByGroup[group], cycle.score_date),
    ])),
  ]));
  const dates = Object.values(rawGroups).flat().map((row) => row.data_date).filter(Boolean).sort();
  const updated = Object.values(rawGroups).flat().map((row) => row.updated_at).filter(Boolean).sort();
  return {
    mode: counts.some(Boolean) ? "live" : "empty",
    version: PUBLIC_API_VERSION,
    scoreModelVersion: SCORE_MODEL_VERSION,
    methodology: "persistent-batched-opportunity-engine-v17-free-public-data",
    generatedAt: updated.at(-1) || null,
    dataDate: Object.values(groupDates).filter(Boolean).sort().at(-1) || dates.at(-1) || null,
    groupDates,
    groups: Object.fromEntries(groups.map((group) => [
      group,
      rawGroups[group].map((row) => {
        const trend = rankingTrendForStoredRow(
          row,
          cyclesByGroup[group],
          scoresByGroup[group],
          scoreRanksByGroup[group],
        );
        return {
          ...normalizeStoredRow(row, groupDates[group]),
          rank: trend.rank,
          previousRank: trend.previousRank,
          rankDelta: trend.rankDelta,
          scoreDelta: trend.scoreDelta,
          trend,
        };
      }),
    ])),
    universe: {
      verifiedCandidates: Object.fromEntries(groups.map((group, index) => [group, counts[index]])),
    },
    backend: {
      persistent: true,
      counts: Object.fromEntries(groups.map((group, index) => [group, counts[index]])),
      sync: states.map(compactSyncState),
      rankingCycles: Object.fromEntries(groups.map((group) => [group, cyclesByGroup[group]])),
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
  const [cacheResult, contextResult] = await Promise.all([
    request(
      `stock_analysis_cache?select=${select}&symbol=eq.${encodeURIComponent(symbol)}&status=eq.ready&analysis_version=eq.${encodeURIComponent(EXPECTED_ANALYSIS_VERSION)}&limit=1`,
    ),
    request(`rpc/twss_get_stock_context?p_symbol=${encodeURIComponent(symbol)}`)
      .catch(() => ({ data: {
        available: false,
        status: "unavailable",
        errorCode: "context_unavailable",
      } })),
  ]);
  const { data } = cacheResult;
  const row = Array.isArray(data) ? data[0] : null;
  if (!row?.analysis) throw new Error(`${symbol} 尚未完成後端深度驗證`);
  const context = rpcObject(contextResult.data, { available: false });
  return {
    mode: "live",
    symbol: String(symbol),
    dataDate: row.data_date || null,
    fetchedAt: row.fetched_at || row.updated_at || null,
    stock: row.stock || {},
    result: row.result || {},
    ...row.analysis,
    context,
    ...(context.available ? {
      peer: context.peer || null,
      trend: context.trend || null,
    } : {}),
  };
}

export async function readDataHealth() {
  const [healthResult, missingResult] = await Promise.all([
    request("rpc/twss_public_data_health"),
    request("rpc/twss_public_missing_data?p_limit=40")
      .catch(() => ({ data: { summary: [], examples: [], status: "unavailable" } })),
  ]);
  return {
    mode: "live",
    ...rpcObject(healthResult.data, {}),
    version: PUBLIC_API_VERSION,
    missingData: rpcObject(missingResult.data, { summary: [], examples: [] }),
  };
}

export async function readRankingBacktest() {
  const { data } = await request(
    `rpc/twss_public_ranking_backtest?p_model_version=${encodeURIComponent(SCORE_MODEL_VERSION)}`,
  );
  return {
    mode: "live",
    ...rpcObject(data, {}),
    version: PUBLIC_API_VERSION,
    scoreModelVersion: SCORE_MODEL_VERSION,
  };
}

export async function readBackendStatus() {
  const { data } = await request(
    "stock_sync_state?select=*&job_key=in.(universe,deep_listed,deep_otc,deep_etf)&order=job_key.asc",
  );
  return {
    mode: "live",
    version: PUBLIC_API_VERSION,
    persistent: true,
    jobs: Array.isArray(data) ? data.map(compactSyncState) : [],
  };
}

export const backendStoreInternals = {
  request,
  countRows,
  normalizeStoredRow,
  compactSyncState,
  safeErrorCode,
  compactRankingStock,
  compactRankingAnalysis,
  rpcObject,
  rankedScores,
  rankingTrend,
  rankingTrendForStoredRow,
};
