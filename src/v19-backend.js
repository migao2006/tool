import {
  backendStoreInternals,
  readBackendAnalysis,
  readBackendRankings,
} from "./backend-store.js";

const API_VERSION = "19.0";
const SCORE_MODEL_VERSION = "16.3";
const GROUPS = ["listed", "otc", "etf"];
const DEFAULT_LIMIT = 10;
const MAX_LIMIT = 100;
const PAGE_TTL_MS = 30_000;
const NEWS_TTL_MS = 30_000;
const JOB_TTL_MS = 15_000;
const SORTS = new Set([
  "score_desc",
  "score_asc",
  "confidence_desc",
  "updated_desc",
  "change_desc",
  "risk_asc",
  "risk_desc",
]);
const MARKET_ALIASES = new Map([
  ["listed", "listed"],
  ["上市", "listed"],
  ["twse", "listed"],
  ["otc", "otc"],
  ["上櫃", "otc"],
  ["tpex", "otc"],
  ["etf", "etf"],
]);

const memoryCache = new Map();
const finite = (value) => value != null && Number.isFinite(Number(value));
const numeric = (value) => finite(value) ? Number(value) : null;
const unique = (values) => [...new Set(values.filter(Boolean))];
const clamp = (value, min = 0, max = 100) => Math.max(min, Math.min(max, Number(value)));
const arrays = (...values) => values.flatMap((value) => Array.isArray(value) ? value : []);
const isoDate = (value) => /^\d{4}-\d{2}-\d{2}/.test(String(value || ""))
  ? String(value).slice(0, 10)
  : null;

export class V19PublicError extends Error {
  constructor(code, status = 400, message = code) {
    super(message);
    this.name = "V19PublicError";
    this.code = code;
    this.status = status;
  }
}

async function cached(key, ttl, loader) {
  const now = Date.now();
  const existing = memoryCache.get(key);
  if (existing?.value !== undefined && existing.expiresAt > now) return existing.value;
  if (existing?.pending) return existing.pending;

  const pending = Promise.resolve()
    .then(loader)
    .then((value) => {
      memoryCache.set(key, { value, expiresAt: Date.now() + ttl });
      return value;
    })
    .catch((error) => {
      if (existing?.value !== undefined) {
        memoryCache.set(key, {
          value: existing.value,
          expiresAt: Date.now() + Math.min(5_000, ttl),
        });
        return existing.value;
      }
      memoryCache.delete(key);
      throw error;
    });
  memoryCache.set(key, { ...existing, pending, expiresAt: existing?.expiresAt || 0 });
  return pending;
}

function deterministicAiScore(score, confidence, precomputed = false, value = null, basis = null) {
  return {
    value: numeric(value) ?? numeric(score),
    confidence: numeric(confidence),
    basis: basis || "v16.3-fixed-weight-composite",
    scoreModelVersion: SCORE_MODEL_VERSION,
    precomputed,
    affectsRanking: true,
  };
}

function categoryProjection(categories, keys, reason) {
  const selected = (Array.isArray(categories) ? categories : [])
    .filter((category) => keys.includes(category?.key) && finite(category?.score));
  const denominator = selected.reduce((sum, item) => sum + Math.max(0, numeric(item.weight) ?? 1), 0);
  const value = denominator > 0
    ? selected.reduce((sum, item) => sum + Number(item.score) * Math.max(0, numeric(item.weight) ?? 1), 0) / denominator
    : null;
  return {
    value: value == null ? null : Number(value.toFixed(2)),
    sourceKeys: selected.map((item) => item.key),
    basis: "v16.3-category-weighted-projection",
    reason: value == null ? reason : null,
  };
}

function factorProjection(categories, keys, reason) {
  const selected = (Array.isArray(categories) ? categories : [])
    .flatMap((category) => Array.isArray(category?.items) ? category.items : [])
    .filter((factor) => keys.includes(factor?.key) && finite(factor?.score));
  const denominator = selected.reduce((sum, item) => sum + Math.max(0, numeric(item.weight) ?? 1), 0);
  const value = denominator > 0
    ? selected.reduce((sum, item) => sum + Number(item.score) * Math.max(0, numeric(item.weight) ?? 1), 0) / denominator
    : null;
  return {
    value: value == null ? null : Number(value.toFixed(2)),
    sourceKeys: selected.map((item) => item.key),
    basis: "v16.3-factor-weighted-projection",
    reason: value == null ? reason : null,
  };
}

function deriveScoreDimensions(score, confidence, categories, risk, result) {
  const deduction = numeric(risk?.deduction);
  const completeness = numeric(result?.historyCoverage);
  return {
    overall: {
      value: numeric(score),
      basis: "v16.3-fixed-weight-composite",
      reason: finite(score) ? null : "composite_unavailable",
    },
    fundamental: categoryProjection(
      categories,
      ["growth", "valuation", "structure", "tracking"],
      "fundamental_categories_unavailable",
    ),
    technical: categoryProjection(
      categories,
      ["technical", "trend"],
      "technical_category_unavailable",
    ),
    institutional: categoryProjection(
      categories,
      ["chip"],
      "institutional_category_not_applicable_or_unavailable",
    ),
    volumeMomentum: factorProjection(
      categories,
      ["volume", "volume_structure", "relative20", "breakout"],
      "volume_momentum_factors_unavailable",
    ),
    news: {
      value: null,
      basis: "official-disclosure-keyword-rule-v1",
      reason: "no_related_official_disclosure",
    },
    risk: {
      value: deduction == null ? null : clamp(100 - deduction),
      severity: deduction == null ? null : clamp(deduction),
      basis: "v16.3-risk-deduction-inverse",
      reason: deduction == null ? "risk_deduction_unavailable" : null,
    },
    confidence: {
      value: numeric(confidence),
      basis: "v16.3-source-coverage-confidence",
      reason: finite(confidence) ? null : "confidence_unavailable",
    },
    completeness: {
      value: completeness,
      basis: "v16.3-history-coverage",
      reason: completeness == null ? "history_coverage_unavailable" : null,
    },
  };
}

function opposingSignals(categories) {
  return (Array.isArray(categories) ? categories : [])
    .flatMap((category) => {
      const weakFactors = (Array.isArray(category?.items) ? category.items : [])
        .filter((factor) => finite(factor?.score) && Number(factor.score) < 40)
        .map((factor) => factor.label || factor.key);
      if (weakFactors.length) return weakFactors;
      return finite(category?.score) && Number(category.score) < 40
        ? [category.label || category.key]
        : [];
    })
    .filter(Boolean)
    .slice(0, 8);
}

function normalizeSnapshotRow(row = {}) {
  const stock = row.stock_summary || row.stock || {};
  const result = row.result_summary || row.result || {};
  const symbol = String(row.symbol || stock.symbol || result.symbol || "");
  const group = String(row.group_name || row.group || result.group || "");
  const score = numeric(row.score ?? result.score);
  const confidence = numeric(row.confidence ?? result.confidence) ?? 0;
  const name = row.name || stock.name || result.name || symbol;
  const market = row.market || stock.market || group;
  const industry = row.industry || stock.industry || null;
  const instrumentType = row.instrument_type || stock.instrumentType || (group === "etf" ? "ETF" : "股票");
  const rank = Number.isInteger(Number(row.rank_position ?? row.rank))
    ? Number(row.rank_position ?? row.rank)
    : null;
  const previousRank = Number.isInteger(Number(row.previous_rank ?? row.previousRank))
    ? Number(row.previous_rank ?? row.previousRank)
    : null;
  const cycleStatus = row.cycle_status || row.cycleStatus || (row.official ? "final" : "provisional");
  const official = Boolean(row.official ?? result.official);
  const categories = Array.isArray(result.categories) ? result.categories : [];
  const risk = result.risk || row.risk || {};
  const scoreDimensions = row.score_dimensions || row.scoreDimensions ||
    deriveScoreDimensions(score, confidence, categories, risk, result);
  const analysisDataDate = isoDate(row.score_date || row.analysisDataDate || row.dataDate);
  const tradeDate = isoDate(row.trade_date || row.tradeDate || stock.priceDate || stock.tradeDate);
  const fetchedAt = row.source_fetched_at || row.fetchedAt || null;
  const sourceUpdatedAt = row.source_updated_at || row.sourceUpdatedAt || row.updatedAt || null;
  const analysisGeneratedAt = row.generated_at || row.analysisGeneratedAt || null;
  const snapshotGeneratedAt = row.generated_at || row.snapshotGeneratedAt || null;

  return {
    symbol,
    name,
    group,
    market,
    industry,
    instrumentType,
    cycleStatus,
    updateStatus: cycleStatus === "final" ? "complete" : official ? "available" : "partial",
    dataDate: analysisDataDate,
    analysisDataDate,
    tradeDate,
    fetchedAt,
    sourceUpdatedAt,
    analysisGeneratedAt,
    snapshotGeneratedAt,
    updatedAt: sourceUpdatedAt || analysisGeneratedAt || snapshotGeneratedAt,
    rank,
    pageRow: numeric(row.page_row),
    previousRank,
    rankDelta: numeric(row.rank_delta ?? row.rankDelta),
    scoreDelta: numeric(row.score_delta ?? row.scoreDelta),
    score,
    confidence,
    official,
    tier: row.tier || result.tier || null,
    riskScore: numeric(row.risk_score ?? scoreDimensions?.risk?.severity),
    scoreDimensions,
    positiveReasons: arrays(result.reasons),
    opposingSignals: opposingSignals(categories),
    riskReasons: unique(arrays(risk.flags, risk.hardReasons)),
    stock: {
      ...stock,
      symbol,
      name,
      market,
      industry,
      instrumentType,
      ...(tradeDate ? { priceDate: tradeDate } : {}),
    },
    result: {
      ...result,
      symbol,
      name,
      group,
      score,
      confidence,
      official,
      tier: row.tier || result.tier || null,
      risk,
      categories,
    },
    aiScore: deterministicAiScore(
      score,
      confidence,
      true,
      row.ai_score,
      row.ai_score_basis,
    ),
  };
}

function publicUpdateStatus(groupStatuses, items = []) {
  const statuses = Object.values(groupStatuses || {});
  if (statuses.length && statuses.every((status) => status === "final")) return "complete";
  if (items.some((item) => item?.official === true)) return "available";
  return "partial";
}

function normalizeLegacyItem(row, group) {
  const result = row.result || {};
  const stock = row.stock || {};
  return normalizeSnapshotRow({
    symbol: stock.symbol || result.symbol,
    name: stock.name || result.name,
    group_name: group,
    cycle_status: result.official ? "final" : "provisional",
    market: stock.market || group,
    industry: stock.industry,
    instrument_type: stock.instrumentType,
    score_date: row.dataDate,
    trade_date: stock.priceDate || stock.tradeDate,
    source_updated_at: row.updatedAt,
    rank_position: row.rank,
    previous_rank: row.previousRank,
    rank_delta: row.rankDelta,
    score_delta: row.scoreDelta,
    score: result.score,
    confidence: result.confidence,
    official: result.official,
    tier: result.tier,
    stock_summary: stock,
    result_summary: result,
    ai_score: result.score,
    ai_score_basis: "v16.3-fixed-weight-composite",
  });
}

function normalizeRpcObject(data, fallback = {}) {
  if (data && typeof data === "object" && !Array.isArray(data)) return data;
  if (Array.isArray(data) && data[0] && typeof data[0] === "object") return data[0];
  return fallback;
}

function parseBoundedText(params, key, maxLength) {
  const value = String(params.get(key) || "").trim();
  if (value.length > maxLength) throw new V19PublicError(`invalid_${key}`);
  return value;
}

function queryFingerprint(query) {
  return JSON.stringify({
    market: query.market,
    industry: query.industry.toLocaleLowerCase("zh-Hant"),
    search: query.search.toLocaleLowerCase("zh-Hant"),
    sort: query.sort,
  });
}

function validGroupDates(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(GROUPS.flatMap((group) => {
    const date = isoDate(value[group]);
    return date ? [[group, date]] : [];
  }));
}

function encodeCursor(offset, fingerprint, groupDates = {}) {
  return Buffer.from(JSON.stringify({
    v: 2,
    o: offset,
    q: fingerprint,
    d: validGroupDates(groupDates),
  }), "utf8").toString("base64url");
}

function decodeCursorState(value, fingerprint) {
  if (!value) return { offset: 0, groupDates: {} };
  try {
    const decoded = JSON.parse(Buffer.from(value, "base64url").toString("utf8"));
    if (![1, 2].includes(decoded.v) || !Number.isInteger(decoded.o) || decoded.o < 0 ||
        decoded.o > 100_000 || decoded.q !== fingerprint) {
      throw new Error("invalid");
    }
    return { offset: decoded.o, groupDates: validGroupDates(decoded.d) };
  } catch {
    throw new V19PublicError("invalid_cursor");
  }
}

function decodeCursor(value, fingerprint) {
  return decodeCursorState(value, fingerprint).offset;
}

export function parseRankingQuery(params) {
  const limitText = params.get("limit");
  const limit = limitText == null || limitText === "" ? DEFAULT_LIMIT : Number(limitText);
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_LIMIT) {
    throw new V19PublicError("invalid_limit");
  }

  const marketInput = String(params.get("market") || "").trim().toLocaleLowerCase("en-US");
  const market = marketInput && marketInput !== "all"
    ? MARKET_ALIASES.get(marketInput)
    : null;
  if (marketInput && marketInput !== "all" && !market) {
    throw new V19PublicError("invalid_market");
  }

  const sort = String(params.get("sort") || "score_desc").trim().toLocaleLowerCase("en-US");
  if (!SORTS.has(sort)) throw new V19PublicError("invalid_sort");

  const query = {
    limit,
    market,
    industry: parseBoundedText(params, "industry", 80),
    search: parseBoundedText(params, "search", 60),
    sort,
  };
  const fingerprint = queryFingerprint(query);
  const cursor = decodeCursorState(params.get("cursor"), fingerprint);
  return { ...query, ...cursor, fingerprint };
}

function pageRpcPath(query) {
  const params = new URLSearchParams({
    p_sort: query.sort,
    p_after_row: String(query.offset),
    p_limit: String(query.limit),
    p_model_version: SCORE_MODEL_VERSION,
  });
  if (query.market) params.set("p_group_name", query.market);
  if (query.industry) params.set("p_industry", query.industry);
  if (query.search) params.set("p_search", query.search);
  if (Object.keys(query.groupDates || {}).length) {
    params.set("p_group_dates", JSON.stringify(query.groupDates));
  }
  return `rpc/twss_v19_rankings_page?${params}`;
}

async function loadRpcPage(query) {
  const { data } = await backendStoreInternals.request(pageRpcPath(query));
  const payload = normalizeRpcObject(data, {});
  if (!Array.isArray(payload.items)) throw new Error("v19_page_unavailable");
  const items = payload.items.map(normalizeSnapshotRow).filter((item) => item.symbol);
  const groupDates = validGroupDates(payload.group_dates);
  const groupStatuses = payload.group_statuses && typeof payload.group_statuses === "object"
    ? payload.group_statuses
    : {};
  return {
    mode: items.length ? "live" : "empty",
    source: "v19-precomputed-page",
    dataDate: Object.values(groupDates).sort().at(-1) || null,
    groupDates,
    groupStatuses,
    generatedAt: payload.snapshot_generated_at || null,
    pageUpdatedAt: payload.page_updated_at || new Date().toISOString(),
    total: Math.max(0, Number(payload.total) || 0),
    lastRow: Math.max(query.offset, Number(payload.last_row) || query.offset),
    hasMore: payload.has_more === true,
    industries: unique(arrays(payload.industries, items.map((item) => item.industry))).sort(),
    items,
    degraded: [],
  };
}

function compareNullable(left, right, direction = "desc") {
  const l = numeric(left);
  const r = numeric(right);
  if (l == null && r == null) return 0;
  if (l == null) return 1;
  if (r == null) return -1;
  return direction === "asc" ? l - r : r - l;
}

function sortItems(items, sort) {
  const bySymbol = (left, right) => left.symbol.localeCompare(right.symbol, "en");
  return [...items].sort((left, right) => {
    if (sort === "score_asc") {
      return compareNullable(left.score, right.score, "asc") ||
        compareNullable(left.confidence, right.confidence) || bySymbol(left, right);
    }
    if (sort === "confidence_desc") {
      return compareNullable(left.confidence, right.confidence) ||
        compareNullable(left.score, right.score) || bySymbol(left, right);
    }
    if (sort === "change_desc") {
      return compareNullable(left.scoreDelta, right.scoreDelta) ||
        compareNullable(left.score, right.score) || bySymbol(left, right);
    }
    if (sort === "risk_asc" || sort === "risk_desc") {
      return compareNullable(left.riskScore, right.riskScore, sort === "risk_asc" ? "asc" : "desc") ||
        compareNullable(left.score, right.score) || bySymbol(left, right);
    }
    if (sort === "updated_desc") {
      const updated = String(right.updatedAt || "").localeCompare(String(left.updatedAt || ""));
      return updated || compareNullable(left.score, right.score) || bySymbol(left, right);
    }
    return compareNullable(left.score, right.score) ||
      compareNullable(left.confidence, right.confidence) || bySymbol(left, right);
  });
}

function filteredItems(items, query) {
  const industry = query.industry.toLocaleLowerCase("zh-Hant");
  const search = query.search.toLocaleLowerCase("zh-Hant");
  return items.filter((item) => {
    if (query.market && item.group !== query.market) return false;
    if (industry && String(item.industry || "").toLocaleLowerCase("zh-Hant") !== industry) return false;
    if (search) {
      const haystack = [item.symbol, item.name, item.industry, item.market]
        .filter(Boolean).join(" ").toLocaleLowerCase("zh-Hant");
      if (!haystack.includes(search)) return false;
    }
    return true;
  });
}

async function loadLegacyPage(query) {
  const legacy = await readBackendRankings(200);
  const all = GROUPS.flatMap((group) =>
    (legacy.groups?.[group] || []).map((row) => normalizeLegacyItem(row, group)));
  const filtered = sortItems(filteredItems(all, query), query.sort);
  const items = filtered.slice(query.offset, query.offset + query.limit);
  const lastRow = query.offset + items.length;
  return {
    mode: items.length ? "degraded" : "empty",
    source: "legacy-ranking-cache",
    dataDate: legacy.dataDate || null,
    groupDates: validGroupDates(legacy.groupDates),
    groupStatuses: {},
    generatedAt: legacy.generatedAt || null,
    pageUpdatedAt: new Date().toISOString(),
    total: filtered.length,
    lastRow,
    hasMore: lastRow < filtered.length,
    industries: unique(filtered.map((item) => item.industry)).sort(),
    items,
    degraded: ["v19_page_unavailable"],
  };
}

async function rankingPage(query) {
  const key = `v19:page:${queryFingerprint(query)}:${query.offset}:${JSON.stringify(query.groupDates || {})}:${query.limit}`;
  return cached(key, PAGE_TTL_MS, async () => {
    try {
      return await loadRpcPage(query);
    } catch {
      return loadLegacyPage(query);
    }
  });
}

export async function readV19Rankings(url) {
  const query = parseRankingQuery(url.searchParams);
  const page = await rankingPage(query);
  return {
    version: API_VERSION,
    scoreModelVersion: SCORE_MODEL_VERSION,
    mode: page.mode,
    source: page.source,
    dataDate: page.dataDate,
    groupDates: page.groupDates,
    groupStatuses: page.groupStatuses,
    generatedAt: page.generatedAt,
    pageUpdatedAt: page.pageUpdatedAt,
    updateStatus: publicUpdateStatus(page.groupStatuses, page.items),
    items: page.items,
    nextCursor: page.hasMore
      ? encodeCursor(page.lastRow, query.fingerprint, page.groupDates)
      : null,
    totalEstimate: page.total,
    filters: {
      market: query.market,
      industry: query.industry || null,
      search: query.search || null,
      limit: query.limit,
      industries: page.industries,
    },
    sort: query.sort,
    degraded: page.degraded,
  };
}

function normalizeNewsRow(row = {}) {
  return {
    id: row.id || null,
    source: row.source || null,
    market: row.market || null,
    symbols: Array.isArray(row.symbols) ? row.symbols.map(String) : [],
    companyName: row.company_name || null,
    title: row.title || "",
    summary: row.summary || "",
    category: row.category || null,
    eventDate: row.event_date || null,
    sentimentLabel: row.sentiment_label || "neutral",
    sentimentScore: numeric(row.sentiment_score) ?? 0,
    sentimentBasis: row.sentiment_basis || "official-disclosure-keyword-rule-v1",
    sentimentTerms: Array.isArray(row.sentiment_terms) ? row.sentiment_terms : [],
    url: row.source_url || row.url || null,
    publishedAt: row.published_at || null,
    fetchedAt: row.fetched_at || null,
    updatedAt: row.updated_at || null,
  };
}

async function loadNews(symbol = null, limit = 30) {
  const params = new URLSearchParams({
    select: "id,source,market,symbols,company_name,title,summary,category,event_date,sentiment_label,sentiment_score,sentiment_basis,sentiment_terms,source_url,published_at,fetched_at,updated_at",
    order: "published_at.desc,id.asc",
    limit: String(Math.max(1, Math.min(50, Number(limit) || 30))),
  });
  if (symbol) params.set("symbols", `cs.{${symbol}}`);
  const { data } = await backendStoreInternals.request(`v19_news_items?${params}`);
  return (Array.isArray(data) ? data : []).map(normalizeNewsRow);
}

async function newsResult(symbol = null, limit = 30) {
  try {
    return {
      items: await cached(`v19:news:${symbol || "all"}:${limit}`, NEWS_TTL_MS, () => loadNews(symbol, limit)),
      degraded: [],
    };
  } catch {
    return { items: [], degraded: ["news_unavailable"] };
  }
}

async function loadJobs() {
  const { data } = await backendStoreInternals.request("rpc/twss_v19_public_job_status");
  const payload = Array.isArray(data) ? data : normalizeRpcObject(data, []);
  return Array.isArray(payload) ? payload.map((job) => ({
    job: String(job.job || ""),
    group: job.group || null,
    status: ["pending", "running", "success", "partial", "error"].includes(job.status)
      ? job.status
      : "pending",
    cycleDate: job.cycleDate || job.cycle_date || null,
    processed: Math.max(0, Number(job.processed) || 0),
    total: Math.max(0, Number(job.total) || 0),
    progress: clamp(Number(job.progress) || 0),
    lastSuccessAt: job.lastSuccessAt || job.last_success_at || null,
    updatedAt: job.updatedAt || job.updated_at || null,
  })).filter((job) => job.job) : [];
}

async function jobsResult() {
  try {
    return {
      items: await cached("v19:jobs", JOB_TTL_MS, loadJobs),
      degraded: [],
    };
  } catch {
    return { items: [], degraded: ["job_status_unavailable"] };
  }
}

function rankingUrl(values) {
  const url = new URL("https://internal.invalid/api/v19/rankings");
  Object.entries(values).forEach(([key, value]) => {
    if (value != null && value !== "") url.searchParams.set(key, String(value));
  });
  return url;
}

export async function readV19Home() {
  const [listed, otc, etf, risers, news, jobs] = await Promise.all([
    readV19Rankings(rankingUrl({ market: "listed", limit: 10, sort: "score_desc" })),
    readV19Rankings(rankingUrl({ market: "otc", limit: 10, sort: "score_desc" })),
    readV19Rankings(rankingUrl({ market: "etf", limit: 10, sort: "score_desc" })),
    readV19Rankings(rankingUrl({ limit: 10, sort: "change_desc" })),
    newsResult(null, 20),
    jobsResult(),
  ]);
  const pageByGroup = { listed, otc, etf };
  const groups = Object.fromEntries(GROUPS.map((group) => [group, pageByGroup[group].items]));
  const ranked = sortItems(Object.values(groups).flat(), "score_desc");
  const groupDates = Object.assign({}, ...GROUPS.map((group) => pageByGroup[group].groupDates || {}));
  const groupStatuses = Object.assign({}, ...GROUPS.map((group) => pageByGroup[group].groupStatuses || {}));
  const degraded = unique([
    ...GROUPS.flatMap((group) => pageByGroup[group].degraded || []),
    ...(risers.degraded || []),
    ...news.degraded,
    ...jobs.degraded,
  ]);
  const dates = Object.values(groupDates).filter(Boolean).sort();
  const generated = GROUPS.map((group) => pageByGroup[group].generatedAt).filter(Boolean).sort();
  const pageUpdated = GROUPS.map((group) => pageByGroup[group].pageUpdatedAt).filter(Boolean).sort();
  const industries = unique(GROUPS.flatMap((group) =>
    pageByGroup[group].filters?.industries || groups[group].map((item) => item.industry))).sort();
  const hasRankings = ranked.length > 0;
  return {
    version: API_VERSION,
    scoreModelVersion: SCORE_MODEL_VERSION,
    mode: hasRankings ? (degraded.length ? "degraded" : "live") : "empty",
    source: "v19-precomputed-pages",
    dataDate: dates.at(-1) || null,
    groupDates,
    groupStatuses,
    generatedAt: generated.at(-1) || null,
    pageUpdatedAt: pageUpdated.at(-1) || new Date().toISOString(),
    updateStatus: publicUpdateStatus(groupStatuses, ranked),
    groups,
    todayPicks: ranked.slice(0, 3),
    fastestRisers: risers.items.filter((item) => finite(item.scoreDelta) && item.scoreDelta > 0),
    rankings: ranked.slice(0, 10),
    news: news.items,
    jobs: jobs.items,
    filters: { industries },
    degraded,
  };
}

async function scoreHistory(symbol) {
  const params = new URLSearchParams({
    select: "score_date,score,confidence,official,created_at",
    symbol: `eq.${symbol}`,
    model_version: `eq.${SCORE_MODEL_VERSION}`,
    order: "score_date.desc",
    limit: "12",
  });
  const { data } = await backendStoreInternals.request(`opportunity_score_history?${params}`);
  return (Array.isArray(data) ? data : []).map((row) => ({
    date: row.score_date,
    score: numeric(row.score),
    confidence: numeric(row.confidence),
    official: row.official === true,
    generatedAt: row.created_at || null,
  }));
}

function newsDimension(items) {
  if (!items.length) {
    return {
      value: null,
      rawSentiment: null,
      basis: "official-disclosure-keyword-rule-v1",
      reason: "no_related_official_disclosure",
    };
  }
  const raw = items.reduce((sum, item) => sum + (numeric(item.sentimentScore) ?? 0), 0) / items.length;
  return {
    value: Number(clamp(50 + raw / 2).toFixed(2)),
    rawSentiment: Number(raw.toFixed(2)),
    basis: "official-disclosure-keyword-rule-v1",
    reason: null,
  };
}

export async function readV19Stock(symbol) {
  const normalizedSymbol = String(symbol || "").trim().toUpperCase();
  if (!/^[0-9]{4,6}[A-Z]?$/.test(normalizedSymbol)) {
    throw new V19PublicError("invalid_symbol");
  }

  const [rankingResult, news, analysisResult, historyResult] = await Promise.all([
    readV19Rankings(rankingUrl({ search: normalizedSymbol, limit: 20, sort: "score_desc" }))
      .catch(() => null),
    newsResult(normalizedSymbol, 30),
    readBackendAnalysis(normalizedSymbol)
      .then((value) => ({ value, degraded: [] }))
      .catch(() => ({ value: null, degraded: ["analysis_unavailable"] })),
    scoreHistory(normalizedSymbol)
      .then((items) => ({ items, degraded: [] }))
      .catch(() => ({ items: [], degraded: ["score_history_unavailable"] })),
  ]);
  const ranking = rankingResult?.items.find((item) => item.symbol.toUpperCase() === normalizedSymbol) || null;
  const analysis = analysisResult.value;
  const result = analysis?.result || ranking?.result || {};
  const categories = Array.isArray(result.categories) ? result.categories : [];
  const risk = result.risk || ranking?.result?.risk || {};
  const baseDimensions = ranking?.scoreDimensions || deriveScoreDimensions(
    result.score,
    result.confidence,
    categories,
    risk,
    result,
  );
  const scoreDimensions = { ...baseDimensions, news: newsDimension(news.items) };
  const positiveReasons = unique(arrays(result.reasons, ranking?.positiveReasons));
  const negativeReasons = unique(arrays(ranking?.opposingSignals, opposingSignals(categories)));
  const riskReasons = unique(arrays(risk.flags, risk.hardReasons, ranking?.riskReasons));
  const industry = analysis?.stock?.industry || ranking?.industry || null;
  let relatedStocks = [];
  if (industry) {
    try {
      const related = await readV19Rankings(rankingUrl({ industry, limit: 7, sort: "score_desc" }));
      relatedStocks = related.items.filter((item) => item.symbol !== normalizedSymbol).slice(0, 6);
    } catch {
      relatedStocks = [];
    }
  }
  const enrichedAnalysis = analysis ? {
    ...analysis,
    scoreDimensions,
    componentScores: scoreDimensions,
    positiveReasons,
    reasons: positiveReasons,
    opposingSignals: negativeReasons,
    negativeSignals: negativeReasons,
    riskReasons,
    risks: riskReasons,
    dataCompleteness: scoreDimensions.completeness,
    scoreHistory: historyResult.items,
  } : {
    scoreDimensions,
    componentScores: scoreDimensions,
    positiveReasons,
    reasons: positiveReasons,
    opposingSignals: negativeReasons,
    negativeSignals: negativeReasons,
    riskReasons,
    risks: riskReasons,
    dataCompleteness: scoreDimensions.completeness,
    scoreHistory: historyResult.items,
  };
  const degraded = unique([
    ...(rankingResult?.degraded || ["ranking_unavailable"]),
    ...news.degraded,
    ...analysisResult.degraded,
    ...historyResult.degraded,
  ]);
  const available = Boolean(ranking || analysis);
  const analysisDataDate = isoDate(ranking?.analysisDataDate || analysis?.dataDate || rankingResult?.dataDate);
  const tradeDate = isoDate(
    ranking?.tradeDate || analysis?.stock?.priceDate || analysis?.stock?.tradeDate,
  );
  const pageUpdatedAt = new Date().toISOString();
  return {
    version: API_VERSION,
    scoreModelVersion: SCORE_MODEL_VERSION,
    mode: available ? (degraded.length ? "degraded" : "live") : "empty",
    symbol: normalizedSymbol,
    dataDate: analysisDataDate,
    analysisDataDate,
    tradeDate,
    newsPublishedAt: news.items[0]?.publishedAt || null,
    fetchedAt: ranking?.fetchedAt || analysis?.fetchedAt || null,
    analysisGeneratedAt: ranking?.analysisGeneratedAt || analysis?.fetchedAt || null,
    pageUpdatedAt,
    updateStatus: ranking?.updateStatus || (available ? "partial" : "unavailable"),
    generatedAt: ranking?.snapshotGeneratedAt || analysis?.fetchedAt || rankingResult?.generatedAt || null,
    stock: analysis?.stock || ranking?.stock || null,
    ranking,
    aiScore: ranking?.aiScore || deterministicAiScore(result.score, result.confidence),
    scoreDimensions,
    positiveReasons,
    negativeReasons,
    riskReasons,
    analysis: enrichedAnalysis,
    news: news.items,
    scoreHistory: historyResult.items,
    relatedStocks,
    degraded,
  };
}

export const v19BackendInternals = {
  API_VERSION,
  SCORE_MODEL_VERSION,
  SORTS,
  normalizeSnapshotRow,
  normalizeLegacyItem,
  deterministicAiScore,
  deriveScoreDimensions,
  encodeCursor,
  decodeCursor,
  decodeCursorState,
  sortItems,
  filteredItems,
  pageRpcPath,
  publicUpdateStatus,
  clearCache() {
    memoryCache.clear();
  },
};
