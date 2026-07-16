import { backendStoreInternals } from "./backend-store.js";
import { readV19Home, readV19Stock } from "./v19-backend.js";
import { readV20GlobalMarket } from "./v20-global-market.js";

const API_VERSION = "20.0";
const MODEL_VERSION = "20.0";
const PAGE_TTL_MS = 30_000;
const MARKET_TTL_MS = 60_000;
const STOCK_TTL_MS = 30_000;
const PUBLICATION_TTL_MS = 2_000;
const MAX_LIMIT = 50;
const MODEL_HORIZONS = Object.freeze({ short: [2, 3, 5, 10], medium: [20, 40, 60] });
const DEFAULT_HORIZON = Object.freeze({ short: 5, medium: 40 });
const RANKING_GROUPS = Object.freeze(["listed", "otc", "etf"]);
const GLOBAL_ALIASES = Object.freeze({
  nasdaq: ["nasdaq"],
  sp500: ["sp500"],
  sox: ["sox"],
  tsmAdr: ["tsmAdr"],
  nvda: ["nvda", "nvidia"],
  vix: ["vix"],
  usTreasury: ["usTreasury", "us10y"],
  twdUsd: ["twdUsd", "usdTwd"],
});
const SORTS = Object.freeze({
  score_desc: "opportunity_score.desc.nullslast,confidence.desc.nullslast,symbol.asc",
  expected_value_desc: "expected_value.desc.nullslast,opportunity_score.desc.nullslast,symbol.asc",
  risk_asc: "risk_score.asc.nullslast,opportunity_score.desc.nullslast,symbol.asc",
  probability_desc: "up_probability.desc.nullslast,expected_value.desc.nullslast,symbol.asc",
  change_desc: "rank_delta.desc.nullslast,opportunity_score.desc.nullslast,symbol.asc",
});
const memoryCache = new Map();
const serverEnv = globalThis.process?.env || {};
const marketServiceKey = String(
  serverEnv.SUPABASE_SECRET_KEY || serverEnv.SUPABASE_SERVICE_ROLE_KEY || "",
).trim();
const PUBLICATION_PHASES = new Set(["cached", "base_ready", "enriching", "complete"]);
const MODEL_FEATURES = Object.freeze({
  short: Object.freeze({
    technicalTrend: ["技術趨勢與型態", 20],
    volumePrice: ["成交量與量價結構", 20],
    institutional: ["法人及籌碼", 15],
    market: ["台股與國際市場", 15],
    industry: ["產業與相對強度", 10],
    news: ["新聞與事件催化", 10],
    fundamentalSafety: ["基本面安全檢查", 5],
    liquidity: ["流動性與執行品質", 5],
  }),
  medium: Object.freeze({
    growthEarnings: ["營收與獲利成長", 25],
    industryTrend: ["產業及族群趨勢", 20],
    institutional: ["法人中期布局", 15],
    mediumTechnical: ["中期技術趨勢", 15],
    valuation: ["估值合理性", 10],
    financialSafety: ["財務安全", 10],
    news: ["新聞與事件催化", 5],
  }),
});
const GATE_DEFINITIONS = Object.freeze({
  data_complete: ["資料完整", "資料完整度與歷史行情已達門檻", "資料完整度或歷史行情未達門檻"],
  tradeable_liquid: ["交易與流動性", "交易狀態及流動性合格", "交易限制、重大風險或流動性未達門檻"],
  market_allowed: ["市場環境", "市場環境允許此策略", "市場環境不允許此策略"],
  trend_structure: ["趨勢結構", "趨勢與均線結構符合策略", "趨勢或均線結構未通過"],
  relative_strength: ["相對強度", "相對大盤或產業強度合格", "相對大盤或產業強度不足"],
  evidence_support: ["實質支撐", "基本面、籌碼或事件具備支撐", "基本面、籌碼與事件支撐不足"],
  positive_expectancy: ["交易條件", "規則計算的期望值與風報比合格", "規則計算的期望值或風報比未達門檻"],
});

const finite = (value) => value != null && Number.isFinite(Number(value));
const numeric = (value) => finite(value) ? Number(value) : null;
const isoDate = (value) => /^\d{4}-\d{2}-\d{2}/.test(String(value || ""))
  ? String(value).slice(0, 10)
  : null;
const arrays = (...values) => values.flatMap((value) => Array.isArray(value) ? value : []);
const unique = (values) => [...new Set(values.filter(Boolean).map(String))];
const clamp = (value, min = 0, max = 100) => Math.max(min, Math.min(max, Number(value)));
const cleanObject = (value) => value && typeof value === "object" && !Array.isArray(value) ? value : {};

function serviceHeaders(key = marketServiceKey) {
  return {
    apikey: key,
    ...(!key.startsWith("sb_secret_") ? { authorization: `Bearer ${key}` } : {}),
  };
}

export class V20PublicError extends Error {
  constructor(code, status = 400, message = code) {
    super(message);
    this.name = "V20PublicError";
    this.code = code;
    this.status = status;
  }
}

async function cached(key, ttl, loader) {
  const now = Date.now();
  const existing = memoryCache.get(key);
  if (existing?.value !== undefined && existing.expiresAt > now) return existing.value;
  if (existing?.pending) return existing.pending;
  const pending = Promise.resolve().then(loader).then((value) => {
    memoryCache.set(key, { value, expiresAt: Date.now() + ttl, stale: false });
    return value;
  }).catch((error) => {
    if (existing?.value !== undefined) {
      memoryCache.set(key, { value: existing.value, expiresAt: Date.now() + Math.min(ttl, 5_000), stale: true });
      return existing.value;
    }
    memoryCache.delete(key);
    throw error;
  });
  memoryCache.set(key, { ...existing, pending, expiresAt: existing?.expiresAt || 0 });
  return pending;
}

function normalizePublication(details = {}) {
  const publishedDataDate = isoDate(details.publishedDataDate);
  const phase = PUBLICATION_PHASES.has(details.publicationPhase)
    ? details.publicationPhase
    : publishedDataDate ? "base_ready" : "cached";
  return {
    publicationPhase: phase,
    publishedDataDate,
    baseCompletedAt: details.baseCompletedAt || null,
    enrichmentCompletedAt: details.enrichmentCompletedAt || null,
    enrichmentPending: Math.max(0, Number(details.enrichmentPending) || 0),
    sourceDates: cleanObject(details.sourceDates),
    dataCompleteness: finite(details.dataCompleteness) ? Number(clamp(details.dataCompleteness).toFixed(2)) : 0,
    publishedAt: details.publishedAt || details.completedCycleAt || null,
  };
}

async function loadPublicationState() {
  return cached("v20:publication", PUBLICATION_TTL_MS, async () => {
    const result = marketServiceKey
      ? await backendStoreInternals.request(
        "stock_sync_state?select=details&job_key=eq.v20_model&limit=1",
        {
          headers: serviceHeaders(),
        },
      )
      : await backendStoreInternals.request("rpc/twss_v20_publication_state", {
        method: "POST",
        body: "{}",
      });
    const details = marketServiceKey
      ? Array.isArray(result.data) ? cleanObject(result.data[0]?.details) : {}
      : cleanObject(result.data);
    return normalizePublication(details);
  }).catch(() => normalizePublication({}));
}

function sourceDatesFromRows(rows) {
  return Object.assign({}, ...rows.map((row) => cleanObject(row?.source_dates || row?.sourceDates)));
}

function publicMeta({
  dataState,
  dataDate,
  sourceDates = {},
  fetchedAt = null,
  completeness = 0,
  degraded = [],
  publication = {},
}) {
  const published = normalizePublication(publication);
  const normalizedCompleteness = finite(completeness) ? Number(clamp(completeness).toFixed(2)) : 0;
  return {
    version: API_VERSION,
    modelVersion: MODEL_VERSION,
    dataState,
    dataDate: isoDate(dataDate) || published.publishedDataDate,
    publishedDataDate: published.publishedDataDate,
    sourceDates: { ...published.sourceDates, ...cleanObject(sourceDates) },
    fetchedAt: fetchedAt || null,
    completeness: normalizedCompleteness,
    publicationPhase: published.publicationPhase,
    baseCompletedAt: published.baseCompletedAt,
    enrichmentCompletedAt: published.enrichmentCompletedAt,
    enrichmentPending: published.enrichmentPending,
    dataCompleteness: published.publishedDataDate
      ? published.dataCompleteness
      : normalizedCompleteness,
    degradedSources: unique(degraded),
  };
}

function normalizeMarket(row = {}) {
  const regimeKey = row.regime || null;
  const regimeLabels = {
    strong_bull: "強勢多頭",
    bull: "偏多",
    bullish: "偏多",
    sideways: "震盪",
    range: "震盪",
    bear: "偏空",
    bearish: "偏空",
    strong_bear: "強勢空頭",
  };
  return {
    dataDate: isoDate(row.data_date),
    regimeKey,
    regime: regimeLabels[regimeKey] || "資料不足",
    regimeScore: numeric(row.regime_score),
    confidence: numeric(row.confidence),
    completeness: numeric(row.completeness),
    status: row.status || "partial",
    taiex: cleanObject(row.taiex),
    tpex: cleanObject(row.tpex),
    txFutures: cleanObject(row.tx_futures),
    breadth: cleanObject(row.breadth),
    institutional: cleanObject(row.institutional),
    globalContext: cleanObject(row.global_context),
    sourceDates: cleanObject(row.source_dates),
    degradedSources: arrays(row.degraded_sources),
    fetchedAt: row.fetched_at || null,
    generatedAt: row.generated_at || null,
    updatedAt: row.updated_at || null,
  };
}

function globalIndicators(row = {}) {
  const context = cleanObject(row.globalContext);
  return Object.values(GLOBAL_ALIASES).flatMap((aliases) => {
    const value = aliases.map((alias) => context[alias]).find((item) => item && typeof item === "object");
    return value ? [value] : [];
  });
}

function usableGlobalIndicator(value) {
  if (!value || typeof value !== "object") return false;
  return numeric(value.value ?? value.close ?? value.index ?? value.price ?? value.settlement) != null;
}

function pruneResolvedDegradedSources(sources, row = {}) {
  const context = cleanObject(row.globalContext);
  const resolvedGlobalKeys = new Set();
  for (const [key, aliases] of Object.entries(GLOBAL_ALIASES)) {
    if (aliases.map((alias) => context[alias]).some(usableGlobalIndicator)) {
      resolvedGlobalKeys.add(`global_${key}`);
    }
  }
  const allGlobalIndicatorsReady = resolvedGlobalKeys.size === Object.keys(GLOBAL_ALIASES).length;
  return unique(sources).filter((source) => {
    if (resolvedGlobalKeys.has(source)) return false;
    if (allGlobalIndicatorsReady && ["international_context", "global_market_context"].includes(source)) return false;
    return true;
  });
}

function carryForwardGlobal(rows) {
  const current = rows[0] || normalizeMarket({});
  if (globalIndicators(current).length >= Object.keys(GLOBAL_ALIASES).length) return current;
  const previous = rows.slice(1).find((row) => globalIndicators(row).length);
  if (!previous) return current;
  const globalDateKeys = new Set(["global", ...Object.values(GLOBAL_ALIASES).flat()]);
  const priorDates = Object.fromEntries(
    Object.entries(previous.sourceDates || {}).filter(([key]) => globalDateKeys.has(key)),
  );
  current.globalContext = { ...previous.globalContext, ...current.globalContext };
  current.sourceDates = { ...priorDates, ...current.sourceDates };
  return current;
}

async function persistGlobalMarket(liveGlobal, token) {
  if (!token || !liveGlobal?.indicators?.length) return false;
  const globalContext = {
    available: true,
    dataState: liveGlobal.dataState,
    dataDate: liveGlobal.dataDate,
    fetchedAt: liveGlobal.fetchedAt,
    completeness: liveGlobal.completeness,
    ...Object.fromEntries(liveGlobal.indicators.map((item) => [item.key, item])),
  };
  await backendStoreInternals.request("rpc/twss_v20_persist_global_context", {
    method: "POST",
    body: JSON.stringify({
      p_token: token,
      p_global_context: globalContext,
      p_source_dates: { ...liveGlobal.sourceDates, global: liveGlobal.dataDate },
      p_degraded_sources: arrays(liveGlobal.degradedSources),
    }),
  });
  return true;
}

function normalizeRanking(row = {}) {
  const model = row.model_key === "medium" ? "medium" : "short";
  const horizon = Number(row.horizon_days) || DEFAULT_HORIZON[model];
  const predictionState = predictionStateFor(row);
  const calibrated = predictionState.status === "calibrated";
  const probabilityBasis = predictionState.basis;
  const forecastState = calibrated
    ? "calibrated"
    : predictionState.status === "not_calibrated"
      ? "quant_bootstrap"
      : "insufficient_history";
  const gateResults = cleanObject(row.gate_results);
  const featureScores = cleanObject(row.feature_scores);
  const forecast = {
    horizon,
    upProbability: calibrated ? numeric(row.up_probability) : null,
    expectedNetReturn: calibrated ? numeric(row.expected_return_net) : null,
    returnRange: {
      p10: calibrated ? numeric(row.return_p10) : null,
      p50: calibrated ? numeric(row.return_p50) : null,
      p90: calibrated ? numeric(row.return_p90) : null,
    },
    averageMfe: calibrated ? numeric(row.mfe) : null,
    averageMae: calibrated ? numeric(row.mae) : null,
    targetFirstProbability: calibrated ? numeric(row.target_first_probability) : null,
    probabilityBasis,
    dataState: forecastState,
    predictionState,
  };
  return {
    symbol: String(row.symbol || ""),
    name: row.name || String(row.symbol || ""),
    model,
    horizon,
    dataDate: isoDate(row.ranking_date || row.signal_date),
    group: row.group_name || null,
    market: row.market || null,
    industry: row.industry || null,
    instrumentType: row.instrument_type || null,
    strategy: row.strategy_key || null,
    rank: numeric(row.rank_position),
    previousRank: numeric(row.previous_rank),
    rankDelta: numeric(row.rank_delta),
    opportunityScore: numeric(row.opportunity_score),
    riskScore: numeric(row.risk_score),
    confidence: numeric(row.confidence),
    completeness: numeric(row.completeness),
    expectedValue: calibrated ? numeric(row.expected_value) : null,
    official: row.official === true,
    gatePassed: row.gate_passed !== false,
    recommendedAction: row.recommended_action || "資料不足",
    summary: row.summary || null,
    reasons: arrays(row.reasons).slice(0, 8),
    risks: arrays(row.risks).slice(0, 8),
    invalidationConditions: arrays(row.invalidation_conditions).slice(0, 8),
    gateResults,
    featureScores,
    predictionState,
    gateReasons: gateReasonsFor(row, predictionState),
    scoreExplanation: scoreExplanationFor(model, featureScores),
    marketImpact: marketImpactFor(model, featureScores),
    forecasts: { [String(horizon)]: forecast },
    tradePlan: {
      entryLow: numeric(row.entry_low),
      entryHigh: numeric(row.entry_high),
      breakoutPrice: numeric(row.breakout_price),
      noChasePrice: numeric(row.no_chase_price),
      stopLoss: numeric(row.stop_loss),
      takeProfit1: numeric(row.take_profit_1),
      takeProfit2: numeric(row.take_profit_2),
      riskRewardRatio: numeric(row.risk_reward_ratio),
      recommendedHoldingDays: numeric(row.recommended_holding_days),
    },
    sourceDates: cleanObject(row.source_dates),
    generatedAt: row.generated_at || null,
    updatedAt: row.updated_at || row.generated_at || null,
    legacyReference: false,
  };
}

function normalizeLegacyRelatedStock(row = {}) {
  const legacyScore = row?.aiScore && typeof row.aiScore === "object"
    ? row.aiScore.value
    : row?.aiScore;
  const opportunityScore = numeric(row?.opportunityScore ?? legacyScore ?? row?.score);
  return {
    ...row,
    symbol: String(row?.symbol || ""),
    opportunityScore,
    aiScore: opportunityScore,
    confidence: numeric(row?.confidence ?? row?.aiScore?.confidence),
    riskScore: numeric(row?.riskScore),
    dataDate: isoDate(row?.dataDate || row?.analysisDataDate),
  };
}

function predictionStateFor(row = {}) {
  const basis = row.prediction_basis || cleanObject(row.gate_results).probabilityBasis || null;
  if (basis === "walk-forward-calibration" && finite(row.up_probability)) {
    return {
      status: "calibrated",
      basis,
      publicForecast: true,
      reason: "已使用 Walk-forward 實際結果完成校準。",
    };
  }
  if (basis === "walk-forward-calibration") {
    return {
      status: "insufficient_history",
      basis,
      publicForecast: false,
      reason: "Walk-forward 校準尚未產生足夠樣本，因此暫不公開機率與報酬。",
    };
  }
  if (basis) {
    return {
      status: "not_calibrated",
      basis,
      publicForecast: false,
      reason: "目前只有量化規則初估，尚未完成 Walk-forward 校準，因此不公開機率、報酬、MFE 與 MAE。",
    };
  }
  return {
    status: "not_generated",
    basis: null,
    publicForecast: false,
    reason: "模型尚未產生預測基礎，或可用歷史樣本不足。",
  };
}

function gateReasonsFor(row = {}, predictionState = predictionStateFor(row)) {
  const values = cleanObject(row.gate_results);
  const rows = Object.entries(GATE_DEFINITIONS).map(([key, [label, passReason, failReason]]) => {
    const value = values[key];
    const status = value === true ? "pass" : value === false ? "fail" : "unknown";
    let reason = status === "pass" ? passReason : status === "fail" ? failReason : `${label}尚無足夠資料可判定`;
    if (key === "positive_expectancy" && predictionState.status !== "calibrated") {
      reason += "；目前僅為內部規則檢查，尚未完成機率校準";
    }
    return { key, label, status, reason };
  });
  const thresholds = [
    ["score_threshold", "機會分數", numeric(row.opportunity_score), (value) => value >= 60, "機會分數需達 60 分"],
    ["risk_threshold", "風險分數", numeric(row.risk_score), (value) => value <= 75, "風險分數需不高於 75 分"],
    ["confidence_threshold", "模型信心", numeric(row.confidence), (value) => value >= 65, "模型信心需達 65% 才能列為正式推薦"],
  ];
  for (const [key, label, value, passed, requirement] of thresholds) {
    rows.push({
      key,
      label,
      status: value == null ? "unknown" : passed(value) ? "pass" : "fail",
      reason: value == null ? `${label}尚無足夠資料可判定` : `${requirement}；目前為 ${value}`,
    });
  }
  return rows;
}

function scoreExplanationFor(model, featureScores = {}) {
  return Object.entries(MODEL_FEATURES[model] || {}).map(([key, [label, weight]]) => {
    const score = numeric(featureScores[key]);
    const effectiveScore = score == null ? 50 : clamp(score);
    return {
      key,
      label,
      score,
      effectiveScore,
      weight,
      contribution: Number((effectiveScore * weight / 100).toFixed(2)),
      dataState: score == null ? "neutral_fallback" : "measured",
    };
  });
}

function marketImpactFor(model, featureScores = {}) {
  if (model === "short") {
    const score = numeric(featureScores.market);
    const effectiveScore = score == null ? 50 : clamp(score);
    return {
      featureKey: "market",
      featureLabel: "台股與國際市場",
      featureScore: score,
      opportunityWeight: 15,
      opportunityContribution: Number((effectiveScore * 0.15).toFixed(2)),
      opportunityDeltaFromNeutral: Number(((effectiveScore - 50) * 0.15).toFixed(2)),
      riskWeight: 15,
      riskContribution: null,
      note: score == null
        ? "市場分項缺少資料，機會分數依既有公式採中性 50 分；風險分項只保存總分，未推測拆分值。"
        : "市場分項占短期機會分數 15%；短期風險模型另有 15% 市場權重，但目前只保存總風險分數。",
    };
  }
  const score = numeric(featureScores.industryTrend);
  return {
    featureKey: "industryTrend",
    featureLabel: "產業及族群趨勢",
    featureScore: score,
    opportunityWeight: 20,
    opportunityContribution: Number(((score == null ? 50 : clamp(score)) * 0.2).toFixed(2)),
    opportunityDeltaFromNeutral: null,
    riskWeight: 10,
    riskContribution: null,
    note: "中期市場因素包含在產業趨勢分項與市場事件風險中；資料庫未保存內部分項，因此不推測個別市場扣加分。",
  };
}

function legacyReference(row, model, horizon) {
  return {
    symbol: row.symbol,
    name: row.name,
    model,
    horizon,
    dataDate: row.dataDate || row.analysisDataDate || null,
    group: row.group,
    market: row.market,
    industry: row.industry,
    instrumentType: row.instrumentType,
    strategy: null,
    rank: null,
    previousRank: null,
    rankDelta: null,
    opportunityScore: null,
    riskScore: null,
    confidence: null,
    completeness: null,
    expectedValue: null,
    official: false,
    gatePassed: false,
    recommendedAction: "資料不足",
    summary: "v20 模型尚在建立，僅顯示最近一次既有資料作為參考。",
    reasons: [],
    risks: ["v20 短中期模型尚未完成校準"],
    invalidationConditions: [],
    forecasts: {
      [String(horizon)]: {
        horizon,
        upProbability: null,
        expectedNetReturn: null,
        returnRange: { p10: null, p50: null, p90: null },
        averageMfe: null,
        averageMae: null,
        targetFirstProbability: null,
        dataState: "insufficient_history",
      },
    },
    tradePlan: {},
    sourceDates: {},
    generatedAt: row.generatedAt || null,
    updatedAt: row.updatedAt || null,
    legacyReference: true,
  };
}

function parseText(params, key, max = 60) {
  const value = String(params.get(key) || "").trim();
  if (value.length > max || /[^0-9A-Za-z\u3400-\u9fff\s._-]/u.test(value)) {
    throw new V20PublicError(`invalid_${key}`);
  }
  return value;
}

function parseModel(params) {
  const model = String(params.get("model") || "short").toLowerCase();
  if (!MODEL_HORIZONS[model]) throw new V20PublicError("invalid_model");
  const horizon = Number(params.get("horizon") || DEFAULT_HORIZON[model]);
  if (!MODEL_HORIZONS[model].includes(horizon)) throw new V20PublicError("invalid_horizon");
  return { model, horizon };
}

function fingerprint(query) {
  return JSON.stringify({
    model: query.model,
    horizon: query.horizon,
    market: query.market,
    industry: query.industry,
    strategy: query.strategy,
    search: query.search,
    sort: query.sort,
  });
}

function encodeCursor(position, query, offset = 0) {
  return Buffer.from(JSON.stringify({
    v: 2,
    r: Number(position),
    o: Number(offset),
    q: fingerprint(query),
    d: isoDate(query.rankingDate),
    g: cleanObject(query.groupDates),
  }), "utf8").toString("base64url");
}

function decodeCursor(value, query) {
  if (!value) return { afterRank: 0, offset: 0, rankingDate: null, groupDates: null };
  try {
    const decoded = JSON.parse(Buffer.from(value, "base64url").toString("utf8"));
    if (decoded.v !== 2 || !Number.isInteger(decoded.r) || decoded.r < 1 ||
      decoded.r > 100_000 || !Number.isInteger(decoded.o) || decoded.o < 0 ||
      decoded.o > 100_000 || decoded.q !== fingerprint(query)) throw new Error("invalid");
    const rawGroupDates = cleanObject(decoded.g);
    const groupDates = Object.fromEntries(Object.entries(rawGroupDates).map(([group, date]) => {
      if (!RANKING_GROUPS.includes(group) || !isoDate(date)) throw new Error("invalid");
      return [group, isoDate(date)];
    }));
    return {
      afterRank: decoded.r,
      offset: decoded.o,
      rankingDate: isoDate(decoded.d),
      groupDates: Object.keys(groupDates).length ? groupDates : null,
    };
  } catch {
    throw new V20PublicError("invalid_cursor");
  }
}

export function parseV20RankingQuery(params) {
  const { model, horizon } = parseModel(params);
  const limit = Number(params.get("limit") || 10);
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_LIMIT) throw new V20PublicError("invalid_limit");
  const sort = String(params.get("sort") || "expected_value_desc").toLowerCase();
  if (!SORTS[sort]) throw new V20PublicError("invalid_sort");
  const market = parseText(params, "market", 20).toLowerCase();
  if (market && !["all", "listed", "otc", "etf", "twse", "tpex"].includes(market)) {
    throw new V20PublicError("invalid_market");
  }
  const explicitDate = isoDate(params.get("rankingDate"));
  const query = {
    model,
    horizon,
    limit,
    sort,
    market: market === "all" ? "" : market,
    industry: parseText(params, "industry", 80),
    strategy: parseText(params, "strategy", 50),
    search: parseText(params, "search", 40),
    rankingDate: explicitDate,
  };
  const cursor = decodeCursor(params.get("cursor"), query);
  if (explicitDate && cursor.rankingDate && explicitDate !== cursor.rankingDate) {
    throw new V20PublicError("invalid_cursor");
  }
  if ((explicitDate || query.market) && cursor.groupDates) throw new V20PublicError("invalid_cursor");
  return {
    ...query,
    rankingDate: explicitDate || cursor.rankingDate,
    afterRank: cursor.afterRank,
    offset: cursor.offset,
    groupDates: cursor.groupDates,
  };
}

function rankingFilters(query, includeDate = true) {
  const params = new URLSearchParams({
    model_key: `eq.${query.model}`,
    horizon_days: `eq.${query.horizon}`,
    model_version: `eq.${MODEL_VERSION}`,
  });
  if (includeDate && query.rankingDate) params.set("ranking_date", `eq.${query.rankingDate}`);
  if (query.market) {
    const group = query.market === "twse" ? "listed" : query.market === "tpex" ? "otc" : query.market;
    params.set("group_name", `eq.${group}`);
  }
  if (query.industry) params.set("industry", `eq.${query.industry}`);
  if (query.strategy) params.set("strategy_key", `eq.${query.strategy}`);
  if (query.search) {
    const term = query.search.replace(/[.*]/g, "");
    params.set("or", `(symbol.ilike.*${term}*,name.ilike.*${term}*)`);
  }
  return params;
}

function rankingCycleFilters(query, group = query.market) {
  const params = new URLSearchParams({
    model_key: `eq.${query.model}`,
    horizon_days: `eq.${query.horizon}`,
    model_version: `eq.${MODEL_VERSION}`,
  });
  if (group) {
    const normalized = group === "twse" ? "listed" : group === "tpex" ? "otc" : group;
    params.set("group_name", `eq.${normalized}`);
  }
  return params;
}

function rankingComparator(sort) {
  const descending = (left, right) => (numeric(right) ?? -Infinity) - (numeric(left) ?? -Infinity);
  const ascending = (left, right) => (numeric(left) ?? Infinity) - (numeric(right) ?? Infinity);
  return (left, right) => {
    const leftForecast = left.forecasts?.[String(left.horizon)] || {};
    const rightForecast = right.forecasts?.[String(right.horizon)] || {};
    let compared = 0;
    if (sort === "score_desc") compared = descending(left.opportunityScore, right.opportunityScore) || descending(left.confidence, right.confidence);
    else if (sort === "risk_asc") compared = ascending(left.riskScore, right.riskScore) || descending(left.opportunityScore, right.opportunityScore);
    else if (sort === "probability_desc") compared = descending(leftForecast.upProbability, rightForecast.upProbability) || descending(left.expectedValue, right.expectedValue);
    else if (sort === "change_desc") compared = descending(left.rankDelta, right.rankDelta) || descending(left.opportunityScore, right.opportunityScore);
    else compared = descending(left.expectedValue, right.expectedValue) || descending(left.opportunityScore, right.opportunityScore);
    return compared || String(left.symbol).localeCompare(String(right.symbol), "en");
  };
}

async function latestGroupRankingDates(query) {
  const entries = await Promise.all(RANKING_GROUPS.map(async (group) => {
    const params = rankingCycleFilters(query, group);
    params.set("select", "ranking_date");
    params.set("order", "ranking_date.desc");
    params.set("limit", "1");
    const { data } = await backendStoreInternals.request(`v20_ranking_snapshots?${params}`);
    return [group, isoDate(Array.isArray(data) ? data[0]?.ranking_date : null)];
  }));
  return Object.fromEntries(entries.filter(([, date]) => date));
}

async function loadMixedDateRankingPage(query, groupDates) {
  const end = Math.min(query.offset + query.limit + 1, 5_000);
  const pages = await Promise.all(Object.entries(groupDates).map(async ([group, rankingDate]) => {
    const params = rankingFilters({ ...query, market: group, rankingDate });
    params.set("select", "*");
    params.set("order", SORTS[query.sort]);
    params.set("limit", String(end));
    const { data } = await backendStoreInternals.request(`v20_ranking_snapshots?${params}`);
    return (Array.isArray(data) ? data : []).map(normalizeRanking).filter((item) => item.symbol);
  }));
  const merged = pages.flat().sort(rankingComparator(query.sort));
  const items = merged.slice(query.offset, query.offset + query.limit);
  return {
    items,
    total: null,
    hasMore: merged.length > query.offset + query.limit,
    rankingDate: Object.values(groupDates).sort().at(-1) || null,
    groupDates,
    // An empty ETF recommendation set is valid when no ETF passes the hard gate.
    missingGroups: RANKING_GROUPS.filter((group) => group !== "etf" && !groupDates[group]),
    paginationMode: "offset",
  };
}

async function latestRankingDate(query) {
  if (query.rankingDate) return query.rankingDate;
  const params = rankingCycleFilters(query);
  params.set("select", "ranking_date");
  params.set("order", "ranking_date.desc");
  params.set("limit", "1");
  const { data } = await backendStoreInternals.request(`v20_ranking_snapshots?${params}`);
  return isoDate(Array.isArray(data) ? data[0]?.ranking_date : null);
}

async function loadRankingPage(query) {
  if (!query.rankingDate && !query.market) {
    const groupDates = query.groupDates || await latestGroupRankingDates(query);
    if (Object.keys(groupDates).length !== RANKING_GROUPS.length || new Set(Object.values(groupDates)).size > 1) {
      return loadMixedDateRankingPage(query, groupDates);
    }
  }
  const rankingDate = await latestRankingDate(query);
  if (!rankingDate) return { items: [], total: 0, hasMore: false, rankingDate: null };
  const datedQuery = { ...query, rankingDate };
  const params = rankingFilters(datedQuery);
  params.set("select", "*");
  const keyset = query.sort === "expected_value_desc";
  params.set("order", keyset ? "rank_position.asc,symbol.asc" : SORTS[query.sort]);
  if (keyset && query.afterRank > 0) params.set("rank_position", `gt.${query.afterRank}`);
  if (!keyset && query.offset > 0) params.set("offset", String(query.offset));
  params.set("limit", String(query.limit + 1));
  const { data } = await backendStoreInternals.request(`v20_ranking_snapshots?${params}`);
  const rawRows = Array.isArray(data) ? data : [];
  const hasMore = rawRows.length > query.limit;
  const rows = rawRows.slice(0, query.limit);
  return {
    items: rows.map(normalizeRanking).filter((item) => item.symbol),
    total: null,
    hasMore,
    rankingDate,
  };
}

async function v19References(model, horizon, limit) {
  try {
    const home = await cached("v20:legacy-home", PAGE_TTL_MS, readV19Home);
    return arrays(home.rankings, home.todayPicks).filter((row, index, all) =>
      row?.symbol && all.findIndex((item) => item?.symbol === row.symbol) === index)
      .slice(0, limit).map((row) => legacyReference(row, model, horizon));
  } catch {
    return [];
  }
}

export async function readV20Rankings(url, options = {}) {
  const parsedQuery = parseV20RankingQuery(url.searchParams);
  const publication = options.publication || await loadPublicationState();
  const query = !parsedQuery.rankingDate && publication.publishedDataDate
    ? { ...parsedQuery, rankingDate: publication.publishedDataDate }
    : parsedQuery;
  const groupDateKey = JSON.stringify(query.groupDates || {});
  const cacheKey = `v20:rank:${fingerprint(query)}:${query.rankingDate || "latest"}:${groupDateKey}:${query.afterRank}:${query.offset}:${query.limit}`;
  let page;
  let degraded = [];
  try {
    page = await cached(cacheKey, PAGE_TTL_MS, () => loadRankingPage(query));
    if (memoryCache.get(cacheKey)?.stale) degraded.push("v20_ranking_cache_stale");
  } catch {
    page = { items: [], total: 0, hasMore: false, rankingDate: null };
    degraded.push("v20_ranking_snapshots");
  }
  degraded.push(...(page.missingGroups || []).map((group) => `v20_ranking_${group}_missing`));
  const unfilteredDefault = !query.market && !query.industry && !query.strategy && !query.search &&
    !query.rankingDate && !query.groupDates && query.sort === "expected_value_desc";
  if (!page.items.length && query.afterRank === 0 && unfilteredDefault) {
    const references = await v19References(query.model, query.horizon, query.limit);
    if (references.length) {
      page = { ...page, items: references, total: references.length, hasMore: false };
      degraded.push("v20_model_not_ready");
    }
  }
  const dates = page.items.map((row) => row.dataDate).filter(Boolean).sort();
  const sourceDates = {
    ...publication.sourceDates,
    ...sourceDatesFromRows(page.items),
    ...Object.fromEntries(Object.entries(page.groupDates || {}).map(([group, date]) => [`ranking_${group}`, date])),
  };
  const fetched = page.items.map((row) => row.updatedAt || row.generatedAt).filter(Boolean).sort().at(-1) || null;
  const completenessValues = page.items.map((row) => row.completeness).filter(finite);
  const completeness = completenessValues.length
    ? completenessValues.reduce((sum, value) => sum + Number(value), 0) / completenessValues.length
    : 0;
  const dataState = page.items.some((row) => !row.legacyReference) ? (degraded.length ? "partial" : "complete") : "partial";
  return {
    ...publicMeta({
      dataState,
      dataDate: page.rankingDate || dates.at(-1),
      sourceDates,
      fetchedAt: fetched,
      completeness,
      degraded,
      publication,
    }),
    model: query.model,
    horizon: query.horizon,
    items: page.items,
    nextCursor: page.hasMore
      ? encodeCursor(
        page.items.at(-1)?.rank,
        {
          ...query,
          rankingDate: page.paginationMode === "offset" ? null : page.rankingDate,
          groupDates: page.paginationMode === "offset" ? page.groupDates : null,
        },
        query.offset + page.items.length,
      )
      : null,
    totalEstimate: page.total,
    filters: {
      market: query.market || null,
      industry: query.industry || null,
      strategy: query.strategy || null,
      search: query.search || null,
      limit: query.limit,
    },
    sort: query.sort,
  };
}

export async function readV20Market(options = {}) {
  let row = null;
  let degraded = [];
  const publication = options.publication || await loadPublicationState();
  const marketCacheKey = `v20:market:${publication.publishedDataDate || "latest"}`;
  try {
    row = await cached(marketCacheKey, MARKET_TTL_MS, async () => {
      const params = new URLSearchParams({ select: "*", model_version: `eq.${MODEL_VERSION}`, order: "data_date.desc", limit: "10" });
      if (publication.publishedDataDate) params.set("data_date", `lte.${publication.publishedDataDate}`);
      const { data } = await backendStoreInternals.request(`v20_market_context?${params}`);
      return carryForwardGlobal((Array.isArray(data) ? data : []).map(normalizeMarket));
    });
    if (memoryCache.get(marketCacheKey)?.stale) degraded.push("v20_market_cache_stale");
  } catch {
    degraded.push("v20_market_context");
  }
  if (!row?.dataDate) {
    row = normalizeMarket({});
    degraded.push("market_regime", "global_market_context");
  }
  degraded.push(...arrays(row.degradedSources));
  let liveGlobal = null;
  if (options.refreshGlobal === true) {
    try {
      liveGlobal = await readV20GlobalMarket({
        force: true,
        previous: { indicators: globalIndicators(row) },
      });
      if (liveGlobal.indicators?.length) {
        row.globalContext = {
          ...row.globalContext,
          ...Object.fromEntries(liveGlobal.indicators.map((item) => [item.key, item])),
        };
        row.sourceDates = { ...row.sourceDates, ...liveGlobal.sourceDates };
        row.fetchedAt = liveGlobal.fetchedAt || row.fetchedAt;
        try {
          await persistGlobalMarket(liveGlobal, options.persistenceToken);
          degraded = degraded.filter((source) => source !== "international_context");
          row.degradedSources = arrays(row.degradedSources).filter((source) => source !== "international_context");
        } catch {
          degraded.push("global_market_persistence");
        }
      }
      degraded.push(...arrays(liveGlobal.degradedSources));
    } catch {
      degraded.push("global_market_context");
    }
  }
  for (const [key, aliases] of Object.entries(GLOBAL_ALIASES)) {
    if (!aliases.some((alias) => row.globalContext?.[alias])) degraded.push(`global_${key}`);
  }
  degraded = pruneResolvedDegradedSources(degraded, row);
  return {
    ...publicMeta({
      dataState: row.dataDate ? (degraded.length ? "partial" : "complete") : "partial",
      dataDate: row.dataDate,
      sourceDates: row.sourceDates,
      fetchedAt: row.fetchedAt || row.updatedAt,
      completeness: row.completeness || 0,
      degraded,
      publication,
    }),
    market: row,
    globalRefresh: liveGlobal,
  };
}

function rankingUrl(model, horizon, limit = 10) {
  return new URL(`https://internal.invalid/api/v20/rankings?model=${model}&horizon=${horizon}&limit=${limit}`);
}

function buildAtomicDailyReport(meta, market, short, medium, legacy) {
  const regimeLabels = {
    strong_bull: "強勢多頭",
    bull: "偏多",
    sideways: "震盪",
    bear: "偏空",
    strong_bear: "強勢空頭",
  };
  const regime = regimeLabels[market?.market?.regimeKey] || market?.market?.regime || "資料整理中";
  const breadth = cleanObject(market?.market?.breadth?.all);
  const institutional = cleanObject(market?.market?.institutional);
  const institutionalNet = numeric(institutional.net);
  const focusRows = arrays(short?.items, medium?.items)
    .filter((row, index, all) => row?.symbol && all.findIndex((item) => item?.symbol === row.symbol) === index)
    .slice(0, 8);
  const industries = new Map();
  for (const row of focusRows) {
    const industry = row.industry || "未分類";
    const current = industries.get(industry) || { industry, count: 0, score: 0 };
    current.count += 1;
    current.score += numeric(row.opportunityScore) || 0;
    industries.set(industry, current);
  }
  const hotIndustries = [...industries.values()]
    .map((item) => ({ ...item, averageScore: Number((item.score / item.count).toFixed(1)) }))
    .sort((left, right) => right.count - left.count || right.averageScore - left.averageScore)
    .slice(0, 5);
  const top = focusRows[0];
  const oneLine = top
    ? `市場環境${regime}；${top.name || top.symbol}目前量化條件相對突出，仍應留意風險與失效條件。`
    : `市場環境${regime}；目前沒有通過完整條件的主要推薦。`;
  const riskItems = unique(focusRows.flatMap((row) => arrays(row.risks)).slice(0, 8));
  const news = arrays(legacy?.news).slice(0, 20);
  const watchStocks = focusRows.map((row) => ({
    symbol: row.symbol,
    name: row.name,
    whyNotice: row.summary || row.recommendedAction || "通過同日量化條件",
    opportunityScore: row.opportunityScore,
    riskScore: row.riskScore,
  }));
  const mainRisks = riskItems.length
    ? riskItems.map((risk) => ({ title: "量化風險", explanation: risk }))
    : [{ title: "資料仍可能補齊", explanation: "背景資料完成後，分數與排序可能同日再次更新。" }];
  return {
    ...meta,
    updateStatus: meta.publicationPhase,
    generatedAt: meta.fetchedAt || new Date().toISOString(),
    source: "v20-atomic-base-report",
    cachedFallback: false,
    report: {
      oneLine,
      marketStrength: {
        level: regime,
        explanation: finite(breadth.advanceRatio)
          ? `上漲家數比率約 ${Number(breadth.advanceRatio).toFixed(1)}%，市場強弱依同日官方資料計算。`
          : "市場廣度仍在補齊，先以已發布的同日資料判斷。",
      },
      institutionalDirection: {
        direction: institutionalNet == null ? "資料不足" : institutionalNet > 0 ? "偏買方" : institutionalNet < 0 ? "偏賣方" : "中性",
        explanation: institutionalNet == null
          ? "法人資料尚未完整。"
          : `三大法人同日合計淨額為 ${institutionalNet.toLocaleString("zh-TW")}，不代表股價一定同方向變動。`,
      },
      hotIndustries,
      watchStocks,
      opportunityStocks: watchStocks,
      mainRisks,
      risks: mainRisks,
      importantNewsAndAnnouncements: news,
      watchlistChanges: [],
    },
  };
}

export async function readV20Home() {
  const publication = await loadPublicationState();
  const [market, short, medium, legacy] = await Promise.all([
    readV20Market({ publication }),
    readV20Rankings(rankingUrl("short", 5, 10), { publication }),
    readV20Rankings(rankingUrl("medium", 40, 10), { publication }),
    cached("v20:legacy-home", PAGE_TTL_MS, readV19Home).catch(() => null),
  ]);
  const degraded = unique([
    ...market.degradedSources,
    ...short.degradedSources,
    ...medium.degradedSources,
    ...(legacy ? [] : ["v19_home_fallback"]),
  ]);
  const dates = [market.dataDate, short.dataDate, medium.dataDate, legacy?.dataDate].filter(Boolean).sort();
  const completeness = [market.completeness, short.completeness, medium.completeness]
    .filter(finite).reduce((sum, value, _index, values) => sum + Number(value) / values.length, 0);
  const meta = publicMeta({
      dataState: short.items.length || medium.items.length ? (degraded.length ? "partial" : "complete") : "error",
      dataDate: publication.publishedDataDate || dates.at(-1),
      sourceDates: { ...market.sourceDates, ...short.sourceDates, ...medium.sourceDates },
      fetchedAt: [market.fetchedAt, short.fetchedAt, medium.fetchedAt].filter(Boolean).sort().at(-1) || null,
      completeness,
      degraded,
      publication,
    });
  return {
    ...meta,
    market: market.market,
    shortTop: short.items.slice(0, 5),
    mediumTop: medium.items.slice(0, 5),
    importantNews: arrays(legacy?.news).slice(0, 20),
    fastestRisers: arrays(legacy?.fastestRisers).slice(0, 5),
    dailyReport: buildAtomicDailyReport(meta, market, short, medium, legacy),
  };
}

async function loadSignals(symbol, dataDate = null) {
  if (marketServiceKey) {
    const params = new URLSearchParams({
      select: "*",
      symbol: `eq.${symbol}`,
      model_version: `eq.${MODEL_VERSION}`,
      limit: "20",
    });
    if (dataDate) params.set("signal_date", `eq.${dataDate}`);
    params.set("order", dataDate
      ? "model_key.asc,horizon_days.asc"
      : "signal_date.desc,model_key.asc,horizon_days.asc");
    try {
      const { data } = await backendStoreInternals.request(`v20_model_signals?${params}`, {
        headers: serviceHeaders(),
      });
      const rows = Array.isArray(data) ? data : [];
      if (rows.length) return rows.map(normalizeRanking);
    } catch {
      // The bounded public RPC below is the safe fallback for a missing,
      // rotated, or temporarily unavailable server credential.
    }
  }
  const params = new URLSearchParams({
    p_symbol: symbol,
    p_model_version: MODEL_VERSION,
  });
  const { data } = await backendStoreInternals.request(`rpc/twss_v20_public_stock_signals?${params}`);
  const rows = Array.isArray(data) ? data : [];
  const latestByKey = new Map();
  for (const row of rows) {
    const key = `${row.model_key}:${row.horizon_days}`;
    if (!latestByKey.has(key)) latestByKey.set(key, row);
  }
  return [...latestByKey.values()].map(normalizeRanking);
}

function modelStateFor(model, signals, publication, queryFailed = false) {
  const label = model === "short" ? "短期" : "中期";
  const modelSignals = signals.filter((row) => row.model === model);
  const availableDataDate = modelSignals.map((row) => row.dataDate).filter(Boolean).sort().at(-1) || null;
  const requestedDataDate = publication.publishedDataDate || null;
  if (modelSignals.length) {
    if (requestedDataDate && availableDataDate !== requestedDataDate) {
      return {
        status: "previous_date",
        requestedDataDate,
        availableDataDate,
        reason: `${requestedDataDate} 的${label}模型尚未完成，暫時顯示 ${availableDataDate || "前一交易日"} 的結果。`,
      };
    }
    return {
      status: "ready",
      requestedDataDate,
      availableDataDate,
      reason: `${label}模型分數與條件已產生；預測機率是否公開依各期間的校準狀態判定。`,
    };
  }
  if (queryFailed) {
    return {
      status: "query_failed",
      requestedDataDate,
      availableDataDate: null,
      reason: `${label}模型資料查詢失敗，既有行情與基本面資料仍可使用。`,
    };
  }
  return {
    status: "not_generated",
    requestedDataDate,
    availableDataDate: null,
    reason: requestedDataDate
      ? `尚未產生 ${requestedDataDate} 的${label}模型訊號；行情資料可能已完整，但該模型工作尚未完成。`
      : `尚未找到可用的${label}模型訊號，可能尚未建立交易日分析。`,
  };
}

export async function readV20Stock(symbol) {
  const normalized = String(symbol || "").trim().toUpperCase();
  if (!/^[0-9]{4,6}[A-Z]?$/.test(normalized)) throw new V20PublicError("invalid_symbol");
  const publication = await loadPublicationState();
  const signalCacheKey = `v20:stock:${normalized}:${publication.publishedDataDate || "latest"}`;
  const [legacyResult, signalsResult] = await Promise.allSettled([
    readV19Stock(normalized),
    cached(signalCacheKey, STOCK_TTL_MS, () => loadSignals(normalized, publication.publishedDataDate)),
  ]);
  const legacy = legacyResult.status === "fulfilled" ? legacyResult.value : null;
  const signals = signalsResult.status === "fulfilled" ? signalsResult.value : [];
  const signalCacheStale = memoryCache.get(signalCacheKey)?.stale === true;
  const signalsPreviousDate = Boolean(
    publication.publishedDataDate && signals.length && signals.some((row) => row.dataDate !== publication.publishedDataDate),
  );
  const degraded = [
    ...(legacy?.degraded || (legacy ? [] : ["v19_stock_detail"])),
    ...(signalsResult.status === "rejected" ? ["v20_model_signals"] : []),
    ...(signalCacheStale ? ["v20_model_signals_cache_stale"] : []),
    ...(signalsPreviousDate ? ["v20_model_signals_previous_date"] : []),
    ...(!signals.length ? ["v20_model_not_ready"] : []),
  ];
  const sourceDates = { ...cleanObject(legacy?.sourceDates), ...sourceDatesFromRows(signals) };
  const dates = [legacy?.dataDate, ...signals.map((row) => row.dataDate)].filter(Boolean).sort();
  const completenessValues = signals.map((row) => row.completeness).filter(finite);
  const completeness = completenessValues.length
    ? completenessValues.reduce((sum, value) => sum + Number(value), 0) / completenessValues.length
    : numeric(legacy?.scoreDimensions?.completeness?.value) || 0;
  return {
    ...publicMeta({
      dataState: signals.length ? (degraded.length ? "partial" : "complete") : legacy ? "partial" : "error",
      dataDate: dates.at(-1),
      sourceDates,
      fetchedAt: signals.map((row) => row.updatedAt).filter(Boolean).sort().at(-1) || legacy?.fetchedAt || null,
      completeness,
      degraded,
      publication,
    }),
    symbol: normalized,
    tradeDate: legacy?.tradeDate || isoDate(legacy?.stock?.priceDate),
    analysisDataDate: legacy?.analysisDataDate || signals.map((row) => row.dataDate).filter(Boolean).sort().at(-1) || null,
    newsPublishedAt: legacy?.newsPublishedAt || arrays(legacy?.news).map((item) => item.publishedAt).filter(Boolean).sort().at(-1) || null,
    analysisGeneratedAt: signals.map((row) => row.generatedAt).filter(Boolean).sort().at(-1) || legacy?.analysisGeneratedAt || null,
    pageUpdatedAt: new Date().toISOString(),
    stock: legacy?.stock || signals[0] || null,
    quote: legacy?.stock || null,
    short: signals.filter((row) => row.model === "short"),
    medium: signals.filter((row) => row.model === "medium"),
    analysis: legacy?.analysis || null,
    news: arrays(legacy?.news),
    relatedStocks: arrays(legacy?.relatedStocks).map(normalizeLegacyRelatedStock),
    modelStates: {
      short: modelStateFor("short", signals, publication, signalsResult.status === "rejected"),
      medium: modelStateFor("medium", signals, publication, signalsResult.status === "rejected"),
    },
    legacyReference: legacy ? {
      scoreDimensions: legacy.scoreDimensions,
      positiveReasons: legacy.positiveReasons,
      negativeReasons: legacy.negativeReasons,
      riskReasons: legacy.riskReasons,
      scoreHistory: legacy.scoreHistory,
    } : null,
  };
}

export async function readV20Backtest(url) {
  const { model, horizon } = parseModel(url.searchParams);
  const strategy = parseText(url.searchParams, "strategy", 50);
  const regime = parseText(url.searchParams, "regime", 50);
  const industry = parseText(url.searchParams, "industry", 80);
  const params = new URLSearchParams({ p_model_key: model, p_horizon_days: String(horizon) });
  if (strategy) params.set("p_strategy_key", strategy);
  if (regime) params.set("p_regime", regime);
  if (industry) params.set("p_industry", industry);
  let summary = [];
  let degraded = [];
  const backtestCacheKey = `v20:backtest:${params}`;
  try {
    const { data } = await cached(backtestCacheKey, PAGE_TTL_MS, () =>
      backendStoreInternals.request(`rpc/twss_v20_public_backtest_summary_v20?${params}`));
    summary = Array.isArray(data) ? data : data && typeof data === "object" ? [data] : [];
    if (memoryCache.get(backtestCacheKey)?.stale) degraded.push("v20_backtest_cache_stale");
  } catch {
    degraded.push("v20_backtest_summary");
  }
  const generatedAt = summary.map((row) => row.generated_at || row.updated_at).filter(Boolean).sort().at(-1) || null;
  const dataDates = summary.map((row) => row.data_date || row.test_end_date).filter(Boolean).sort();
  return {
    ...publicMeta({
      dataState: summary.length ? (degraded.length ? "partial" : "complete") : "partial",
      dataDate: dataDates.at(-1),
      sourceDates: {},
      fetchedAt: generatedAt,
      completeness: summary.length ? 100 : 0,
      degraded,
    }),
    model,
    horizon,
    methodology: "walk-forward-point-in-time-next-session-execution",
    noLookAhead: true,
    filters: { strategy: strategy || null, regime: regime || null, industry: industry || null },
    summary,
  };
}

export const v20BackendInternals = {
  API_VERSION,
  MODEL_VERSION,
  MODEL_HORIZONS,
  SORTS,
  normalizeMarket,
  normalizeRanking,
  predictionStateFor,
  gateReasonsFor,
  scoreExplanationFor,
  marketImpactFor,
  modelStateFor,
  normalizeLegacyRelatedStock,
  legacyReference,
  encodeCursor,
  decodeCursor,
  publicMeta,
  pruneResolvedDegradedSources,
  normalizePublication,
  loadPublicationState,
  loadSignals,
  clearCache() { memoryCache.clear(); },
};
