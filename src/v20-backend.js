import { backendStoreInternals } from "./backend-store.js";
import { readV20GlobalMarket } from "./v20-global-market.js";
import {
  MEDIUM_WEIGHTS,
  SHORT_WEIGHTS,
} from "../supabase/functions/_shared/v20-opportunity-policy.js";

const API_VERSION = "20.2.1";
const MODEL_VERSION = "20.2";
const PAGE_TTL_MS = 30_000;
const MARKET_TTL_MS = 60_000;
const STOCK_TTL_MS = 30_000;
const PUBLICATION_TTL_MS = 2_000;
const PROVIDER_CONFIG_TTL_MS = 5 * 60_000;
const FUGLE_QUOTE_TTL_MS = 5 * 60_000;
const FUGLE_TIMEOUT_MS = 4_000;
const MAX_LIMIT = 50;
const MIN_PUBLIC_CALIBRATION_SAMPLES = 100;
const MODEL_HORIZONS = Object.freeze({ short: [2, 3, 5, 10], medium: [10, 20, 40] });
const DEFAULT_HORIZON = Object.freeze({ short: 5, medium: 40 });
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
  net_opportunity_desc: "net_opportunity_score.desc.nullslast,rank_position.asc,symbol.asc",
  score_desc: "raw_opportunity_score.desc.nullslast,net_opportunity_score.desc.nullslast,symbol.asc",
  risk_asc: "risk_score.asc.nullslast,net_opportunity_score.desc.nullslast,symbol.asc",
  change_desc: "rank_delta.desc.nullslast,net_opportunity_score.desc.nullslast,symbol.asc",
});
const memoryCache = new Map();
const serverEnv = globalThis.process?.env || {};
const marketServiceKey = String(
  serverEnv.MARKET_SUPABASE_SERVICE_ROLE_KEY || serverEnv.MARKET_SUPABASE_SECRET_KEY
  || serverEnv.SUPABASE_SERVICE_ROLE_KEY || serverEnv.SUPABASE_SECRET_KEY || "",
).trim();
const PUBLICATION_PHASES = new Set(["cached", "base_ready", "enriching", "complete"]);
const MODEL_FEATURES_V21 = Object.freeze({
  short: Object.freeze({
    priceVolumeTrend: ["價量與趨勢結構", SHORT_WEIGHTS.priceVolumeTrend],
    institutional: ["法人籌碼", SHORT_WEIGHTS.institutional],
    relativeIndustry: ["相對強弱與產業動能", SHORT_WEIGHTS.relativeIndustry],
    volatilityRiskReward: ["波動與風險報酬", SHORT_WEIGHTS.volatilityRiskReward],
    marketGlobal: ["市場及美股環境", SHORT_WEIGHTS.marketGlobal],
    revenueEventCatalyst: ["營收與事件催化", SHORT_WEIGHTS.revenueEventCatalyst],
    liquidityExecutionCost: ["流動性與交易成本", SHORT_WEIGHTS.liquidityExecutionCost],
  }),
  medium: Object.freeze({
    revenueProfitGrowth: ["營收與獲利成長", MEDIUM_WEIGHTS.revenueProfitGrowth],
    financialQuality: ["財務品質", MEDIUM_WEIGHTS.financialQuality],
    mediumTrend: ["中期趨勢", MEDIUM_WEIGHTS.mediumTrend],
    institutionalPositioning: ["法人與籌碼", MEDIUM_WEIGHTS.institutionalPositioning],
    industryEnvironment: ["產業環境", MEDIUM_WEIGHTS.industryEnvironment],
    valuationReasonableness: ["估值合理性", MEDIUM_WEIGHTS.valuationReasonableness],
    liquidityRisk: ["流動性與風險", MEDIUM_WEIGHTS.liquidityRisk],
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

function serviceRequest(path, options = {}) {
  if (!marketServiceKey) throw new V20PublicError("backend_not_configured", 503);
  return backendStoreInternals.request(path, {
    ...options,
    headers: { ...serviceHeaders(), ...cleanObject(options.headers) },
  });
}

function publicRpcRequest(name, args = {}) {
  return backendStoreInternals.request(`rpc/${name}`, {
    method: "POST",
    body: JSON.stringify(args),
  });
}

function compareVersions(left, right) {
  const a = String(left || "").split(".").map((part) => Number(part) || 0);
  const b = String(right || "").split(".").map((part) => Number(part) || 0);
  for (let index = 0; index < Math.max(a.length, b.length); index += 1) {
    if ((a[index] || 0) !== (b[index] || 0)) return (b[index] || 0) - (a[index] || 0);
  }
  return 0;
}

async function loadInternalProviderConfig() {
  if (!marketServiceKey) return {};
  return cached("v20:provider-config", PROVIDER_CONFIG_TTL_MS, async () => {
    const { data } = await serviceRequest("rpc/twss_v20_internal_provider_config", {
      method: "POST",
      body: "{}",
    });
    if (Array.isArray(data)) return cleanObject(data[0]);
    return cleanObject(data);
  });
}

async function loadFugleQuote(symbol) {
  if (!marketServiceKey || typeof globalThis.fetch !== "function") return null;
  return cached(`v20:fugle-quote:${symbol}`, FUGLE_QUOTE_TTL_MS, async () => {
    const config = await loadInternalProviderConfig();
    const apiKey = String(config.fugleMarketDataApiKey || "").trim();
    if (!apiKey) return null;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FUGLE_TIMEOUT_MS);
    try {
      const response = await globalThis.fetch(
        `https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/${encodeURIComponent(symbol)}`,
        {
          cache: "no-store",
          signal: controller.signal,
          headers: { accept: "application/json", "x-api-key": apiKey },
        },
      );
      if (!response.ok) return null;
      const payload = cleanObject(await response.json());
      const tradeDate = isoDate(payload.date);
      const close = numeric(payload.lastPrice ?? payload.closePrice);
      if (!tradeDate || close == null || close <= 0 || String(payload.symbol || "") !== symbol) return null;
      return {
        stock: {
          symbol,
          name: payload.name || symbol,
          market: payload.market || null,
          priceDate: tradeDate,
        },
        quote: {
          tradeDate,
          close,
          change: numeric(payload.changePercent),
          changePoints: numeric(payload.change),
          open: numeric(payload.openPrice),
          high: numeric(payload.highPrice),
          low: numeric(payload.lowPrice),
          volume: numeric(payload.total?.tradeVolume),
          value: numeric(payload.total?.tradeValue),
          source: "Fugle MarketData",
          isClosed: payload.isClose === true,
        },
        fetchedAt: payload.lastUpdated || payload.closeTime || new Date().toISOString(),
      };
    } finally {
      clearTimeout(timer);
    }
  }).catch(() => null);
}

function rpcRow(row = {}) {
  const normalized = Object.fromEntries(Object.entries(cleanObject(row)).map(([key, value]) => [
    key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`),
    value,
  ]));
  if (normalized.expected_return_net == null && normalized.expected_net_return != null) {
    normalized.expected_return_net = normalized.expected_net_return;
  }
  return { ...normalized, ...row };
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
  const publishedDataDate = isoDate(details.publishedDataDate || details.data_date || details.dataDate);
  const phase = PUBLICATION_PHASES.has(details.publicationPhase)
    ? details.publicationPhase
    : details.status === "published" ? "complete" : publishedDataDate ? "base_ready" : "cached";
  return {
    runId: numeric(details.runId ?? details.run_id),
    publicationKey: details.publicationKey || details.publication_key || null,
    contentHash: details.contentHash || details.content_hash || null,
    revision: numeric(details.revision),
    modelVersion: details.modelVersion || details.model_version || MODEL_VERSION,
    featureVersion: details.featureVersion || details.feature_version || null,
    costModelVersion: details.costModelVersion || details.cost_model_version || null,
    calibrationVersion: details.calibrationVersion || details.calibration_version || null,
    publicationPhase: phase,
    publishedDataDate,
    baseCompletedAt: details.baseCompletedAt || null,
    enrichmentCompletedAt: details.enrichmentCompletedAt || null,
    enrichmentPending: Math.max(0, Number(details.enrichmentPending) || 0),
    sourceDates: cleanObject(details.sourceDates || cleanObject(details.source_manifest).sourceDates),
    sourceManifest: cleanObject(details.sourceManifest || details.source_manifest),
    marketContext: cleanObject(details.marketContext || details.market_context_snapshot),
    dataCompleteness: finite(details.dataCompleteness ?? details.cycle_completeness)
      ? Number(clamp(details.dataCompleteness ?? details.cycle_completeness).toFixed(2))
      : 0,
    expectedSymbolCount: numeric(details.expected_symbol_count),
    scoredSymbolCount: numeric(details.scored_symbol_count),
    publishedAt: details.publishedAt || details.published_at || details.completedCycleAt || null,
  };
}

function publicationCacheIdentity(publication = {}) {
  const runId = numeric(publication.runId ?? publication.run_id);
  const publicationKey = String(publication.publicationKey || publication.publication_key || "").trim();
  if (runId != null) return `run-${runId}${publicationKey ? `-${publicationKey}` : ""}`;
  if (publicationKey) return `key-${publicationKey}`;
  return "unpublished";
}

async function loadPublicPublicationState() {
  const { data } = await publicRpcRequest("twss_v20_read_publication_state");
  return normalizePublication(rpcRow(data));
}

async function loadPublicationState() {
  return cached("v20:publication", PUBLICATION_TTL_MS, async () => {
    try {
      if (!marketServiceKey) return loadPublicPublicationState();
      const { data: headRows } = await serviceRequest(
        "v20_publication_head?select=run_id,publication_key,content_hash,data_date,revision,published_at,updated_at&audience=eq.public&limit=1",
      );
      const head = Array.isArray(headRows) ? cleanObject(headRows[0]) : {};
      if (head.run_id) {
        const { data: runRows } = await serviceRequest(
          `v20_recommendation_runs?select=*&id=eq.${Number(head.run_id)}&limit=1`,
        );
        const run = Array.isArray(runRows) ? cleanObject(runRows[0]) : {};
        return normalizePublication({ ...run, ...head, status: "published" });
      }
    } catch {
      // An immutable publication is all-or-nothing. Never substitute the
      // mutable worker state when the publication head or run cannot be read.
    }
    return loadPublicPublicationState().catch(() => normalizePublication({}));
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
    modelVersion: published.modelVersion || MODEL_VERSION,
    runId: published.runId,
    publicationKey: published.publicationKey,
    contentHash: published.contentHash,
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

function immutableQuoteFor(row = {}, gateResults = {}, sourceManifest = {}, sourceDates = {}) {
  const itemTradeDate = isoDate(
    row.trade_date || row.tradeDate || row.price_date || row.priceDate || sourceDates.price,
  );
  const manifestTradeDate = isoDate(
    cleanObject(sourceManifest.sourceDates || sourceManifest.source_dates).price,
  );
  const candidates = [
    // quoteSnapshot is copied into the immutable recommendation item and is
    // therefore the strongest available point-in-time quote evidence.
    [cleanObject(gateResults.quoteSnapshot || gateResults.quote_snapshot), null],
    [cleanObject(
      row.quote_snapshot || row.quoteSnapshot || row.quote
      || row.price_snapshot || row.priceSnapshot,
    ), itemTradeDate],
    [cleanObject(
      sourceManifest.quoteSnapshot || sourceManifest.quote_snapshot || sourceManifest.quote
      || sourceManifest.priceSnapshot || sourceManifest.price_snapshot,
    ), manifestTradeDate],
    [row, itemTradeDate],
  ];

  for (const [snapshot, fallbackTradeDate] of candidates) {
    const tradeDate = isoDate(
      snapshot.tradeDate || snapshot.trade_date || snapshot.priceDate || snapshot.price_date
      || snapshot.dataDate || snapshot.data_date || snapshot.date || fallbackTradeDate,
    );
    const close = numeric(snapshot.close ?? snapshot.price);
    if (!tradeDate || close == null || close <= 0) continue;
    return {
      tradeDate,
      close,
      change: numeric(
        snapshot.change ?? snapshot.changePercent ?? snapshot.change_percent ?? snapshot.change_pct,
      ),
      open: numeric(snapshot.open),
      high: numeric(snapshot.high),
      low: numeric(snapshot.low),
      volume: numeric(snapshot.volume),
      value: numeric(snapshot.value ?? snapshot.tradeValue ?? snapshot.trade_value),
      source: typeof snapshot.source === "string" && snapshot.source.trim()
        ? snapshot.source.trim()
        : null,
    };
  }
  return null;
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
  await serviceRequest("rpc/twss_v20_persist_global_context", {
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
  const rawHorizon = row.horizon_days ?? row.horizon;
  const horizon = model === "medium" && String(rawHorizon).toLowerCase() === "blend"
    ? "blend"
    : Number(rawHorizon) || DEFAULT_HORIZON[model];
  const predictionState = predictionStateFor(row);
  const calibrated = predictionState.status === "calibrated";
  const probabilityBasis = predictionState.basis;
  const forecastState = calibrated
    ? "calibrated"
    : predictionState.status === "not_calibrated"
      ? "not_calibrated"
      : "insufficient_history";
  const gateResults = cleanObject(row.gate_results || row.gates);
  const featureScores = cleanObject(row.feature_scores || row.features);
  const sourceManifest = cleanObject(row.source_manifest || row.sourceManifest);
  const sourceDates = cleanObject(
    row.source_dates || row.sourceDates || sourceManifest.sourceDates || sourceManifest.source_dates,
  );
  const quote = immutableQuoteFor(row, gateResults, sourceManifest, sourceDates);
  const tradeDate = quote?.tradeDate || isoDate(
    row.trade_date || row.tradeDate || row.price_date || row.priceDate || sourceDates.price,
  );
  const signalGeneratedAt = sourceManifest.signalGeneratedAt
    || sourceManifest.signal_generated_at || null;
  const signalUpdatedAt = sourceManifest.signalUpdatedAt
    || sourceManifest.signal_updated_at || null;
  const analysisGeneratedAt = signalGeneratedAt || signalUpdatedAt;
  const calibratedProbability = numeric(row.calibrated_up_probability ?? row.up_probability);
  const expectedExcessReturnGross = calibrated
    ? numeric(row.expected_excess_return_gross ?? row.expected_return_gross)
    : null;
  const expectedNetReturn = calibrated
    ? numeric(row.expected_return_net)
    : null;
  const expectedExcessReturnNet = calibrated
    ? numeric(row.expected_excess_return_net)
    : null;
  const rawOpportunityScore = numeric(row.raw_opportunity_score ?? row.opportunity_score);
  const netOpportunityScore = numeric(row.net_opportunity_score ?? row.opportunity_score);
  const referenceOnly = row.outside_publication === true || row.reference_only === true;
  const forecast = {
    horizon,
    upProbability: calibrated ? calibratedProbability : null,
    expectedNetReturn,
    expectedExcessReturnGross,
    expectedExcessReturnNet,
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
    runId: numeric(row.run_id),
    modelVersion: row.model_version || null,
    symbol: String(row.symbol || ""),
    name: row.name || String(row.symbol || ""),
    model,
    horizon,
    dataDate: isoDate(row.ranking_date || row.signal_date),
    tradeDate,
    quote,
    analysisGeneratedAt,
    group: row.group_name || null,
    market: row.market || null,
    industry: row.industry || null,
    instrumentType: row.instrument_type || null,
    strategy: row.strategy_key || null,
    rank: numeric(row.rank_position),
    previousRank: numeric(row.previous_rank),
    rankDelta: numeric(row.rank_delta),
    marketPercentile: numeric(row.market_percentile),
    rawOpportunityScore,
    netOpportunityScore,
    opportunityScore: netOpportunityScore,
    componentHorizons: cleanObject(row.component_horizons || row.componentHorizons),
    blendWeights: cleanObject(row.blend_weights || row.blendWeights),
    riskScore: numeric(row.risk_score),
    confidence: numeric(row.confidence),
    completeness: numeric(row.completeness),
    expectedNetReturn,
    expectedExcessReturnGross,
    expectedExcessReturnNet,
    expectedValue: expectedNetReturn,
    official: row.is_eligible === true || row.official === true,
    gatePassed: Object.hasOwn(row, "is_eligible")
      ? row.is_eligible === true
      : row.gate_passed === true,
    publicVisible: row.public_visible !== false,
    researchOnly: row.research_only === true,
    publicationMembership: !referenceOnly,
    referenceOnly,
    liquidityGrade: row.liquidity_grade || "unknown",
    opportunityState: row.opportunity_state || null,
    calibrationSampleCount: numeric(row.calibration_sample_count),
    executionCosts: {
      commissionPct: numeric(row.estimated_commission_pct),
      taxPct: numeric(row.estimated_tax_pct),
      slippagePct: numeric(row.estimated_slippage_pct),
      spreadPct: numeric(row.estimated_spread_pct),
      totalPct: numeric(row.estimated_total_cost_pct),
    },
    penalties: {
      downside: numeric(row.downside_penalty_score),
      turnover: numeric(row.turnover_penalty_score),
      cost: numeric(row.cost_penalty_score),
      turnoverExposure: numeric(row.turnover_exposure),
    },
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
    sourceDates,
    sourceManifest,
    inputHash: row.input_hash || null,
    generatedAt: signalGeneratedAt || row.generated_at || row.recorded_at || null,
    updatedAt: signalUpdatedAt || row.updated_at || row.recorded_at || row.generated_at || null,
    legacyReference: referenceOnly,
  };
}

function predictionStateFor(row = {}) {
  const basis = row.prediction_basis || cleanObject(row.gate_results).probabilityBasis || null;
  const calibrationSampleCount = numeric(row.calibration_sample_count);
  const calibratedProbability = numeric(row.calibrated_up_probability ?? row.up_probability);
  const isWalkForward = ["walk-forward-calibration", "walk_forward_calibration"].includes(basis);
  if (isWalkForward && finite(calibratedProbability)
    && calibrationSampleCount >= MIN_PUBLIC_CALIBRATION_SAMPLES) {
    return {
      status: "calibrated",
      basis: "walk-forward-calibration",
      publicForecast: true,
      sampleCount: calibrationSampleCount,
      reason: `已完成 Walk-forward 樣本外校準（樣本 ${calibrationSampleCount}）。`,
    };
  }
  if (isWalkForward) {
    return {
      status: "insufficient_history",
      basis: "walk-forward-calibration",
      publicForecast: false,
      sampleCount: calibrationSampleCount,
      reason: `Walk-forward 樣本不足 ${MIN_PUBLIC_CALIBRATION_SAMPLES}，不公開機率。`,
    };
  }
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
    [
      "score_threshold",
      "成本後機會分數",
      numeric(row.net_opportunity_score ?? row.opportunity_score),
      (value) => value >= 60,
      "成本後機會分數需達 60 分",
    ],
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
  return Object.entries(MODEL_FEATURES_V21[model] || {}).map(([key, [label, weight]]) => {
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
    const score = numeric(featureScores.marketGlobal);
    const effectiveScore = score == null ? 50 : clamp(score);
    return {
      featureKey: "marketGlobal",
      featureLabel: "市場及美股環境",
      featureScore: score,
      opportunityWeight: SHORT_WEIGHTS.marketGlobal,
      opportunityContribution: Number((effectiveScore * SHORT_WEIGHTS.marketGlobal / 100).toFixed(2)),
      opportunityDeltaFromNeutral: Number(((effectiveScore - 50) * SHORT_WEIGHTS.marketGlobal / 100).toFixed(2)),
      riskWeight: 15,
      riskContribution: null,
      note: score == null
        ? "市場分項缺少資料，機會分數依既有公式採中性 50 分；風險分項只保存總分，未推測拆分值。"
        : "市場及美股環境占短期機會分數 10%；風險仍由獨立風險模型評估。",
    };
  }
  const score = numeric(featureScores.industryEnvironment);
  return {
    featureKey: "industryEnvironment",
    featureLabel: "產業環境",
    featureScore: score,
    opportunityWeight: MEDIUM_WEIGHTS.industryEnvironment,
    opportunityContribution: Number(((score == null ? 50 : clamp(score)) * MEDIUM_WEIGHTS.industryEnvironment / 100).toFixed(2)),
    opportunityDeltaFromNeutral: null,
    riskWeight: 10,
    riskContribution: null,
    note: "產業環境占中期機會分數 10%；未保存的內部分項不做推測。",
  };
}

function parseText(params, key, max = 60) {
  const value = String(params.get(key) || "").trim();
  if (value.length > max || /[^0-9A-Za-z\u3400-\u9fff\s._-]/u.test(value)) {
    throw new V20PublicError(`invalid_${key}`);
  }
  return value;
}

function parseModel(params, options = {}) {
  const model = String(params.get("model") || "short").toLowerCase();
  if (!MODEL_HORIZONS[model]) throw new V20PublicError("invalid_model");
  const requestedHorizon = String(params.get("horizon") || DEFAULT_HORIZON[model]).toLowerCase();
  const horizon = options.allowBlend && model === "medium" && requestedHorizon === "blend"
    ? "blend"
    : Number(requestedHorizon);
  if (horizon !== "blend" && !MODEL_HORIZONS[model].includes(horizon)) {
    throw new V20PublicError("invalid_horizon");
  }
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
    v: 3,
    r: Number(position),
    o: Number(offset),
    q: fingerprint(query),
    d: isoDate(query.rankingDate),
    p: query.publicationKey || null,
  }), "utf8").toString("base64url");
}

function decodeCursor(value, query) {
  if (!value) return {
    afterRank: 0,
    offset: 0,
    rankingDate: null,
    publicationKey: null,
  };
  try {
    const decoded = JSON.parse(Buffer.from(value, "base64url").toString("utf8"));
    if (decoded.v !== 3 || !Number.isInteger(decoded.r) || decoded.r < 1 ||
      decoded.r > 100_000 || !Number.isInteger(decoded.o) || decoded.o < 0 ||
      decoded.o > 100_000 || decoded.q !== fingerprint(query) ||
      !/^[0-9a-f]{64}$/.test(String(decoded.p || ""))) throw new Error("invalid");
    return {
      afterRank: decoded.r,
      offset: decoded.o,
      rankingDate: isoDate(decoded.d),
      publicationKey: decoded.p,
    };
  } catch {
    throw new V20PublicError("invalid_cursor");
  }
}

export function parseV20RankingQuery(params) {
  const { model, horizon } = parseModel(params, { allowBlend: true });
  const limit = Number(params.get("limit") || 10);
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_LIMIT) throw new V20PublicError("invalid_limit");
  const sort = String(params.get("sort") || "net_opportunity_desc").toLowerCase();
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
  return {
    ...query,
    rankingDate: explicitDate || cursor.rankingDate,
    afterRank: cursor.afterRank,
    offset: cursor.offset,
    publicationKey: cursor.publicationKey,
  };
}

function normalizeRpcRanking(row, runId) {
  const normalized = rpcRow(row);
  return normalizeRanking({
    ...normalized,
    run_id: normalized.run_id ?? runId,
    expected_return_net: normalized.expected_return_net ?? normalized.expected_net_return,
    is_eligible: normalized.is_eligible ?? true,
    public_visible: normalized.public_visible ?? true,
    research_only: normalized.research_only ?? false,
  });
}

function isPublicModelHorizon(item) {
  if (item?.model === "medium" && item?.horizon === "blend") return true;
  return MODEL_HORIZONS[item?.model]?.includes(Number(item?.horizon)) === true;
}

function compareNullable(left, right, direction = "desc") {
  const leftMissing = left == null || !Number.isFinite(Number(left));
  const rightMissing = right == null || !Number.isFinite(Number(right));
  if (leftMissing || rightMissing) return leftMissing === rightMissing ? 0 : leftMissing ? 1 : -1;
  return direction === "asc" ? Number(left) - Number(right) : Number(right) - Number(left);
}

function sortPublicRankings(rows, sort) {
  return [...rows].sort((left, right) => {
    let order = 0;
    if (sort === "risk_asc") order = compareNullable(left.riskScore, right.riskScore, "asc");
    else if (sort === "change_desc") order = compareNullable(left.rankDelta, right.rankDelta);
    else if (sort === "score_desc") order = compareNullable(left.rawOpportunityScore, right.rawOpportunityScore);
    else order = compareNullable(left.netOpportunityScore, right.netOpportunityScore);
    if (order) return order;
    order = compareNullable(left.netOpportunityScore, right.netOpportunityScore);
    return order || left.symbol.localeCompare(right.symbol, "en");
  });
}

async function loadMediumBlendPage(query) {
  const keyset = query.sort === "net_opportunity_desc";
  const requiresCompleteSet = !keyset || Boolean(query.strategy || query.search);
  const groupName = query.market === "twse" ? "listed" : query.market === "tpex" ? "otc" : query.market || null;
  const baseQuery = {
    runId: query.runId,
    groupName,
    industry: query.industry || null,
  };
  const readPage = async (afterRank, limit) => {
    const { data } = await publicRpcRequest("twss_v20_read_medium_blend", {
      p_query: { ...baseQuery, afterRank, limit },
    });
    return cleanObject(data);
  };

  if (!requiresCompleteSet) {
    const payload = await readPage(query.afterRank, query.limit);
    const run = cleanObject(payload.run);
    return {
      items: arrays(payload.items)
        .map((row) => normalizeRpcRanking(row, query.runId))
        .filter((item) => item.symbol && item.model === "medium" && item.horizon === "blend"
          && item.publicVisible && !item.researchOnly && item.official && item.gatePassed),
      total: numeric(payload.total),
      hasMore: payload.hasMore === true,
      rankingDate: isoDate(run.dataDate || run.data_date) || query.rankingDate,
      runId: numeric(run.runId ?? run.run_id) || query.runId,
      paginationMode: "keyset",
    };
  }

  const collected = [];
  let afterRank = 0;
  let run = {};
  for (let page = 0; page < 100; page += 1) {
    const payload = await readPage(afterRank, 200);
    run = cleanObject(payload.run);
    collected.push(...arrays(payload.items));
    if (payload.hasMore !== true) break;
    const nextAfterRank = numeric(payload.nextAfterRank ?? payload.next_after_rank);
    if (!nextAfterRank || nextAfterRank <= afterRank) throw new Error("invalid_public_blend_cursor");
    afterRank = nextAfterRank;
    if (page === 99) throw new Error("public_blend_page_limit_exceeded");
  }
  const search = query.search.replace(/[.*]/g, "").toLocaleLowerCase("en");
  const filtered = collected
    .map((row) => normalizeRpcRanking(row, query.runId))
    .filter((item) => item.symbol && item.model === "medium" && item.horizon === "blend"
      && item.publicVisible && !item.researchOnly && item.official && item.gatePassed)
    .filter((item) => !query.strategy || item.strategy === query.strategy)
    .filter((item) => !search || `${item.symbol} ${item.name}`.toLocaleLowerCase("en").includes(search));
  const sorted = sortPublicRankings(filtered, query.sort);
  const items = sorted.slice(query.offset, query.offset + query.limit);
  return {
    items,
    total: filtered.length,
    hasMore: query.offset + items.length < filtered.length,
    rankingDate: isoDate(run.dataDate || run.data_date) || query.rankingDate,
    runId: numeric(run.runId ?? run.run_id) || query.runId,
    paginationMode: "offset",
  };
}

async function loadPublicRankingPage(query) {
  const keyset = query.sort === "net_opportunity_desc";
  const requiresCompleteSet = !keyset || Boolean(query.strategy || query.search);
  const groupName = query.market === "twse" ? "listed" : query.market === "tpex" ? "otc" : query.market || null;
  const baseQuery = {
    modelKey: query.model,
    horizonDays: query.horizon,
    runId: query.runId,
    groupName,
    industry: query.industry || null,
  };

  if (!requiresCompleteSet) {
    const { data } = await publicRpcRequest("twss_v20_read_rankings", {
      p_query: { ...baseQuery, afterRank: query.afterRank, limit: query.limit },
    });
    const payload = cleanObject(data);
    const run = cleanObject(payload.run);
    return {
      items: arrays(payload.items)
        .map((row) => normalizeRpcRanking(row, query.runId))
        .filter((item) => item.symbol && isPublicModelHorizon(item)
          && item.model === query.model && item.horizon === query.horizon
          && item.publicVisible && !item.researchOnly && item.official),
      total: null,
      hasMore: payload.hasMore === true,
      rankingDate: isoDate(run.dataDate || run.data_date) || query.rankingDate,
      runId: numeric(run.runId ?? run.run_id) || query.runId,
      paginationMode: "keyset",
    };
  }

  const collected = [];
  let afterRank = keyset ? query.afterRank : 0;
  let run = {};
  for (let page = 0; page < 100; page += 1) {
    const { data } = await publicRpcRequest("twss_v20_read_rankings", {
      p_query: { ...baseQuery, afterRank, limit: 200 },
    });
    const payload = cleanObject(data);
    run = cleanObject(payload.run);
    collected.push(...arrays(payload.items));
    if (payload.hasMore !== true) break;
    const nextAfterRank = numeric(payload.nextAfterRank ?? payload.next_after_rank);
    if (!nextAfterRank || nextAfterRank <= afterRank) throw new Error("invalid_public_ranking_cursor");
    afterRank = nextAfterRank;
    if (page === 99) throw new Error("public_ranking_page_limit_exceeded");
  }

  const search = query.search.replace(/[.*]/g, "").toLocaleLowerCase("en");
  const filtered = collected
    .map((row) => normalizeRpcRanking(row, query.runId))
    .filter((item) => item.symbol && isPublicModelHorizon(item)
      && item.model === query.model && item.horizon === query.horizon
      && item.publicVisible && !item.researchOnly && item.official)
    .filter((item) => !query.strategy || item.strategy === query.strategy)
    .filter((item) => !search || `${item.symbol} ${item.name}`.toLocaleLowerCase("en").includes(search));
  const sorted = sortPublicRankings(filtered, query.sort);
  const offset = keyset ? 0 : query.offset;
  const items = sorted.slice(offset, offset + query.limit);
  return {
    items,
    total: null,
    hasMore: offset + items.length < sorted.length,
    rankingDate: isoDate(run.dataDate || run.data_date) || query.rankingDate,
    runId: numeric(run.runId ?? run.run_id) || query.runId,
    paginationMode: keyset ? "keyset" : "offset",
  };
}

async function loadRankingPage(query) {
  if (!query.runId) {
    return { items: [], total: 0, hasMore: false, rankingDate: null, runId: null };
  }
  if (query.model === "medium" && query.horizon === "blend") return loadMediumBlendPage(query);
  if (!marketServiceKey) return loadPublicRankingPage(query);
  const params = new URLSearchParams({
    select: "*",
    run_id: `eq.${query.runId}`,
    model_key: `eq.${query.model}`,
    horizon_days: `eq.${query.horizon}`,
    public_visible: "eq.true",
    research_only: "eq.false",
    is_eligible: "eq.true",
  });
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
  const keyset = query.sort === "net_opportunity_desc";
  params.set("order", keyset ? "rank_position.asc,symbol.asc" : SORTS[query.sort]);
  if (keyset && query.afterRank > 0) params.set("rank_position", `gt.${query.afterRank}`);
  if (!keyset && query.offset > 0) params.set("offset", String(query.offset));
  params.set("limit", String(query.limit + 1));

  let data;
  try {
    ({ data } = await serviceRequest(`v20_recommendation_items?${params}`));
  } catch {
    return loadPublicRankingPage(query);
  }
  const rawRows = (Array.isArray(data) ? data : []).filter((row) =>
    row.public_visible === true && row.research_only !== true && row.is_eligible === true);
  const hasMore = rawRows.length > query.limit;
  const rows = rawRows.slice(0, query.limit);
  return {
    items: rows.map(normalizeRanking).filter((item) => item.symbol),
    total: null,
    hasMore,
    rankingDate: query.rankingDate || null,
    runId: query.runId,
  };
}

export async function readV20Rankings(url, options = {}) {
  const parsedQuery = parseV20RankingQuery(url.searchParams);
  const publication = options.publication || await loadPublicationState();
  if (parsedQuery.rankingDate && publication.publishedDataDate
    && parsedQuery.rankingDate !== publication.publishedDataDate) {
    throw new V20PublicError("stale_ranking_cursor");
  }
  if (parsedQuery.publicationKey && parsedQuery.publicationKey !== publication.publicationKey) {
    throw new V20PublicError("stale_ranking_cursor");
  }
  const query = {
    ...parsedQuery,
    runId: publication.runId,
    publicationKey: publication.publicationKey,
    rankingDate: publication.publishedDataDate || parsedQuery.rankingDate,
    groupDates: null,
  };
  const groupDateKey = JSON.stringify(query.groupDates || {});
  const cacheKey = `v20:rank:${publicationCacheIdentity(publication)}:${fingerprint(query)}:${query.rankingDate || "latest"}:${groupDateKey}:${query.afterRank}:${query.offset}:${query.limit}`;
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
  if (!publication.runId) degraded.push("immutable_publication_not_ready");
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
    scoreSemantics: {
      rawOpportunityScore: { deprecated: false, basis: "pre_cost_risk_adjustment" },
      netOpportunityScore: { deprecated: false, basis: "cost_risk_adjusted" },
      opportunityScore: { deprecated: true, aliasOf: "netOpportunityScore" },
    },
  };
}

export async function readV20Market(options = {}) {
  let row = null;
  let degraded = [];
  const publication = options.publication || await loadPublicationState();
  const marketCacheKey = `v20:market:${publicationCacheIdentity(publication)}`;
  try {
    row = await cached(marketCacheKey, MARKET_TTL_MS, async () => {
      const snapshot = cleanObject(publication.marketContext || publication.market_context_snapshot);
      if (!publication.runId || !Object.keys(snapshot).length) {
        throw new Error("immutable_market_context_not_ready");
      }
      return normalizeMarket(snapshot);
    });
    if (memoryCache.get(marketCacheKey)?.stale) degraded.push("v20_market_cache_stale");
  } catch {
    degraded.push("immutable_market_context_not_ready");
  }
  if (!row?.dataDate) {
    row = normalizeMarket({});
    degraded.push("market_regime", "global_market_context");
  }
  degraded.push(...arrays(row.degradedSources));
  let globalRefresh = null;
  if (options.refreshGlobal === true) {
    try {
      const liveGlobal = await readV20GlobalMarket({
        force: true,
        previous: { indicators: globalIndicators(row) },
      });
      const persisted = liveGlobal.indicators?.length
        ? await persistGlobalMarket(liveGlobal, options.persistenceToken).catch(() => false)
        : false;
      globalRefresh = {
        attempted: true,
        persisted,
        availableOnNextPublication: persisted,
      };
    } catch {
      globalRefresh = { attempted: true, persisted: false, availableOnNextPublication: false };
    }
  }
  for (const [key, aliases] of Object.entries(GLOBAL_ALIASES)) {
    if (!aliases.some((alias) => row.globalContext?.[alias])) degraded.push(`global_${key}`);
  }
  row.degradedSources = pruneResolvedDegradedSources(row.degradedSources, row);
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
    globalRefresh,
  };
}

function rankingUrl(model, horizon, limit = 10) {
  return new URL(`https://internal.invalid/api/v20/rankings?model=${model}&horizon=${horizon}&limit=${limit}`);
}

function buildAtomicDailyReport(meta, market, short, medium) {
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
  const watchStocks = focusRows.map((row) => ({
    symbol: row.symbol,
    name: row.name,
    whyNotice: row.summary || row.recommendedAction || "通過同日量化條件",
    rawOpportunityScore: row.rawOpportunityScore,
    netOpportunityScore: row.netOpportunityScore,
    opportunityScore: row.opportunityScore,
    riskScore: row.riskScore,
  }));
  const mainRisks = riskItems.length
    ? riskItems.map((risk) => ({ title: "量化風險", explanation: risk }))
    : [{
      title: "資料仍可能補齊",
      explanation: "目前批次保持不變；資料補齊後會發布可追溯的新修訂批次。",
    }];
  return {
    ...meta,
    updateStatus: meta.publicationPhase,
    generatedAt: meta.fetchedAt || new Date().toISOString(),
    title: "每日市場摘要",
    source: "v20-deterministic-market-summary",
    generationMethod: "deterministic_rules",
    aiGenerated: false,
    publicationSemantics: "immutable_revision",
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
      importantNewsAndAnnouncements: [],
      importantNewsState: {
        status: "not_recorded_in_publication",
        reason: "此推薦批次尚未保存可驗證的新聞與公告快照。",
      },
      watchlistChanges: [],
    },
  };
}

export async function readV20Home() {
  const publication = await loadPublicationState();
  const [market, short, medium] = await Promise.all([
    readV20Market({ publication }),
    readV20Rankings(rankingUrl("short", 5, 10), { publication }),
    readV20Rankings(rankingUrl("medium", "blend", 10), { publication }),
  ]);
  const degraded = unique([
    ...market.degradedSources,
    ...short.degradedSources,
    ...medium.degradedSources,
  ]);
  const dates = [market.dataDate, short.dataDate, medium.dataDate].filter(Boolean).sort();
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
    importantNews: [],
    importantNewsState: {
      status: "not_recorded_in_publication",
      reason: "此推薦批次尚未保存可驗證的新聞與公告快照。",
    },
    dailyReport: buildAtomicDailyReport(meta, market, short, medium),
  };
}

async function loadPublicSignals(symbol, publication) {
  const { data } = await publicRpcRequest("twss_v20_read_stock_snapshot", {
    p_query: { symbol, runId: publication.runId },
  });
  const payload = cleanObject(data);
  return arrays(payload.items)
    .map((row) => normalizeRpcRanking(row, publication.runId))
    .filter((item) => item.symbol && isPublicModelHorizon(item)
      && item.publicVisible && !item.researchOnly);
}

async function loadSignals(symbol, publication = {}) {
  if (!publication.runId) return [];
  if (!marketServiceKey) return loadPublicSignals(symbol, publication);
  const params = new URLSearchParams({
    select: "*",
    run_id: `eq.${publication.runId}`,
    symbol: `eq.${symbol}`,
    public_visible: "eq.true",
    research_only: "eq.false",
    order: "model_key.asc,horizon_days.asc",
    limit: "20",
  });
  let data;
  try {
    ({ data } = await serviceRequest(`v20_recommendation_items?${params}`));
  } catch {
    return loadPublicSignals(symbol, publication);
  }
  return (Array.isArray(data) ? data : [])
    .filter((row) => row.public_visible === true && row.research_only !== true)
    .map(normalizeRanking);
}

async function loadReferenceSignals(symbol, publication = {}) {
  if (!marketServiceKey) return [];
  const params = new URLSearchParams({
    select: "*",
    symbol: `eq.${symbol}`,
    order: "signal_date.desc,model_version.desc,model_key.asc,horizon_days.asc",
    limit: "80",
  });
  if (publication.publishedDataDate) params.set("signal_date", `lte.${publication.publishedDataDate}`);
  const { data } = await serviceRequest(`v20_model_signals?${params}`);
  const rows = Array.isArray(data) ? data : [];
  const publicRows = rows.filter((row) => {
    const horizons = MODEL_HORIZONS[row.model_key];
    return Array.isArray(horizons) && horizons.includes(Number(row.horizon_days))
      && row.research_only !== true;
  });
  if (!publicRows.length) return [];
  const candidates = [...new Set(publicRows.map((row) => `${isoDate(row.signal_date)}|${row.model_version || ""}`))]
    .map((key) => {
      const [date, version] = key.split("|");
      return { date, version };
    })
    .sort((left, right) => String(right.date).localeCompare(String(left.date))
      || compareVersions(left.version, right.version));
  const selected = candidates[0];
  return publicRows
    .filter((row) => isoDate(row.signal_date) === selected.date
      && String(row.model_version || "") === selected.version)
    .map((row) => normalizeRanking({
      ...row,
      outside_publication: true,
      source_manifest: {
        ...cleanObject(row.source_manifest),
        referenceOnly: true,
        referenceReason: "outside_current_publication",
      },
    }));
}

async function loadLatestStockSnapshot(symbol, publication = {}) {
  if (!marketServiceKey) return null;
  const params = new URLSearchParams({
    select: "symbol,trade_date,close,change_pct,volume,open,high,low,trade_value,market,industry,instrument_type,source,source_dates,raw_data,updated_at",
    symbol: `eq.${symbol}`,
    order: "trade_date.desc",
    limit: "1",
  });
  if (publication.publishedDataDate) params.set("trade_date", `lte.${publication.publishedDataDate}`);
  const { data } = await serviceRequest(`stock_snapshots?${params}`);
  const row = Array.isArray(data) ? data[0] : null;
  if (!row) return null;
  const raw = cleanObject(row.raw_data);
  const tradeDate = isoDate(row.trade_date);
  const close = numeric(row.close);
  return {
    stock: {
      symbol,
      name: raw.name || symbol,
      market: row.market || raw.market || null,
      industry: row.industry || raw.industry || null,
      instrumentType: row.instrument_type || raw.instrumentType || null,
      priceDate: tradeDate,
      close,
    },
    quote: tradeDate && close != null && close > 0 ? {
      tradeDate,
      close,
      change: numeric(row.change_pct),
      open: numeric(row.open),
      high: numeric(row.high),
      low: numeric(row.low),
      volume: numeric(row.volume),
      value: numeric(row.trade_value),
      source: row.source || "TWSE/TPEx stored snapshot",
    } : null,
    sourceDates: cleanObject(row.source_dates),
    fetchedAt: row.updated_at || null,
  };
}

function newestQuote(...quotes) {
  return quotes.filter((quote) => quote?.tradeDate && finite(quote.close))
    .sort((left, right) => String(right.tradeDate).localeCompare(String(left.tradeDate)))[0] || null;
}

function modelStateFor(model, signals, publication, options = {}) {
  const label = model === "short" ? "短期" : "中期";
  const modelSignals = signals.filter((row) => row.model === model);
  const availableDataDate = modelSignals.map((row) => row.dataDate).filter(Boolean).sort().at(-1) || null;
  const requestedDataDate = publication.publishedDataDate || null;
  if (modelSignals.length) {
    if (options.referenceOnly) {
      const modelVersion = modelSignals.map((row) => row.modelVersion).filter(Boolean)
        .sort(compareVersions)[0] || "前一模型";
      return {
        status: "outside_publication",
        requestedDataDate,
        availableDataDate,
        modelVersion,
        reason: `此股票不在目前不可修改推薦批次內；以下僅顯示 ${availableDataDate || "最近交易日"}、模型 ${modelVersion} 的參考分析，不代表本批次推薦。`,
      };
    }
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
  if (options.queryFailed) {
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

export async function readV20Stock(symbol, options = {}) {
  const normalized = String(symbol || "").trim().toUpperCase();
  if (!/^[0-9]{4,6}[A-Z]?$/.test(normalized)) throw new V20PublicError("invalid_symbol");
  const publication = options.publication || await loadPublicationState();
  const signalCacheKey = `v20:stock:${normalized}:${publicationCacheIdentity(publication)}`;
  const [signalsResult, snapshotResult, fugleResult] = await Promise.all([
    Promise.resolve(cached(signalCacheKey, STOCK_TTL_MS, () => loadSignals(normalized, publication))).then(
      (value) => ({ status: "fulfilled", value }),
      (reason) => ({ status: "rejected", reason }),
    ),
    loadLatestStockSnapshot(normalized, publication).catch(() => null),
    loadFugleQuote(normalized).catch(() => null),
  ]);
  const immutableSignals = signalsResult.status === "fulfilled" ? signalsResult.value : [];
  const referenceSignals = immutableSignals.length
    ? []
    : await cached(
      `v20:stock-reference:${normalized}:${publication.publishedDataDate || "latest"}`,
      STOCK_TTL_MS,
      () => loadReferenceSignals(normalized, publication),
    ).catch(() => []);
  const signals = immutableSignals.length ? immutableSignals : referenceSignals;
  const referenceOnly = !immutableSignals.length && referenceSignals.length > 0;
  const publicationMember = immutableSignals.length > 0;
  const signalCacheStale = memoryCache.get(signalCacheKey)?.stale === true;
  const signalsPreviousDate = Boolean(
    publication.publishedDataDate && signals.length && signals.some((row) => row.dataDate !== publication.publishedDataDate),
  );
  const degraded = [
    ...(signalsResult.status === "rejected" ? ["v20_model_signals"] : []),
    ...(signalCacheStale ? ["v20_model_signals_cache_stale"] : []),
    ...(signalsPreviousDate ? ["v20_model_signals_previous_date"] : []),
    ...(referenceOnly ? ["outside_current_publication"] : []),
    ...(!signals.length ? ["v20_model_not_generated"] : []),
  ];
  const sourceDates = {
    ...cleanObject(snapshotResult?.sourceDates),
    ...sourceDatesFromRows(signals),
    ...(fugleResult?.quote?.tradeDate ? { quote: fugleResult.quote.tradeDate } : {}),
  };
  const dates = signals.map((row) => row.dataDate).filter(Boolean).sort();
  const completenessValues = signals.map((row) => row.completeness).filter(finite);
  const completeness = completenessValues.length
    ? completenessValues.reduce((sum, value) => sum + Number(value), 0) / completenessValues.length
    : 0;
  const stock = {
    symbol: normalized,
    name: normalized,
    ...cleanObject(snapshotResult?.stock),
    ...cleanObject(signals[0]),
    ...cleanObject(fugleResult?.stock),
  };
  const quotes = signals.map((row) => row.quote).filter((value) =>
    value?.tradeDate && finite(value.close));
  const quoteSignatures = new Set(quotes.map((value) => JSON.stringify(value)));
  const quoteConflict = quoteSignatures.size > 1;
  if (quoteConflict) degraded.push("immutable_quote_conflict");
  const immutableQuote = quoteConflict ? null : quotes[0] || null;
  const quote = newestQuote(fugleResult?.quote, snapshotResult?.quote, immutableQuote);
  if (!quote) degraded.push("quote_unavailable");
  const tradeDate = quote?.tradeDate
    || signals.map((row) => row.tradeDate).filter(Boolean).sort().at(-1)
    || null;
  return {
    ...publicMeta({
      dataState: signals.length || quote ? (degraded.length ? "partial" : "complete") : "error",
      dataDate: publication.publishedDataDate || dates.at(-1),
      sourceDates,
      fetchedAt: [
        ...signals.map((row) => row.updatedAt),
        snapshotResult?.fetchedAt,
        fugleResult?.fetchedAt,
      ].filter(Boolean).sort().at(-1) || null,
      completeness,
      degraded,
      publication,
    }),
    symbol: normalized,
    tradeDate,
    analysisDataDate: signals.map((row) => row.dataDate).filter(Boolean).sort().at(-1) || null,
    newsPublishedAt: null,
    analysisGeneratedAt: signals.map((row) => row.analysisGeneratedAt)
      .filter(Boolean).sort().at(-1) || null,
    pageUpdatedAt: new Date().toISOString(),
    stock,
    quote,
    quoteState: {
      status: quote ? "ready" : "unavailable",
      source: quote?.source || null,
      dataDate: quote?.tradeDate || null,
      independentFromModelPublication: Boolean(quote && quote.tradeDate !== publication.publishedDataDate),
    },
    publicationCoverage: {
      member: publicationMember,
      status: publicationMember ? "included" : referenceOnly ? "outside_current_publication" : "model_not_generated",
      runId: publication.runId || null,
      referenceSignalsUsed: referenceOnly,
      referenceModelVersion: referenceOnly
        ? signals.map((row) => row.modelVersion).filter(Boolean).sort(compareVersions)[0] || null
        : null,
    },
    short: signals.filter((row) => row.model === "short"),
    medium: signals.filter((row) => row.model === "medium"),
    analysis: null,
    news: [],
    newsState: {
      status: "not_recorded_in_publication",
      reason: "此推薦批次尚未保存可驗證的個股新聞快照。",
    },
    relatedStocks: [],
    modelStates: {
      short: modelStateFor("short", signals, publication, {
        queryFailed: signalsResult.status === "rejected",
        referenceOnly,
      }),
      medium: modelStateFor("medium", signals, publication, {
        queryFailed: signalsResult.status === "rejected",
        referenceOnly,
      }),
    },
    legacyReference: null,
  };
}

export async function readV20Backtest(url) {
  const { model, horizon } = parseModel(url.searchParams);
  const strategy = parseText(url.searchParams, "strategy", 50);
  const regime = parseText(url.searchParams, "regime", 50);
  const industry = parseText(url.searchParams, "industry", 80);
  const topN = Number(url.searchParams.get("topN") || 50);
  if (!Number.isInteger(topN) || topN < 1 || topN > 500) throw new V20PublicError("invalid_topN");
  const publication = await loadPublicationState();
  let result = {
    status: "insufficient_data",
    source: "immutable_forward_observations",
    sampleCount: 0,
    minimumSampleCount: 100,
    sufficient: false,
    topN,
    items: [],
  };
  let degraded = [];
  const query = {
    modelKey: model,
    horizonDays: horizon,
    modelVersion: publication.modelVersion || MODEL_VERSION,
    strategyKey: strategy || null,
    marketRegime: regime || null,
    industry: industry || null,
    topN,
    minimumSampleCount: 100,
  };
  const backtestCacheKey = `v20:validation:${JSON.stringify(query)}`;
  try {
    const { data } = await cached(backtestCacheKey, PAGE_TTL_MS, async () => {
      if (marketServiceKey) {
        try {
          return await serviceRequest("rpc/twss_v20_read_validation_summary", {
            method: "POST",
            body: JSON.stringify({ p_query: query }),
          });
        } catch {
          // Fall through to the bounded public read RPC.
        }
      }
      return publicRpcRequest("twss_v20_read_validation_summary", { p_query: query });
    });
    if (data && typeof data === "object" && !Array.isArray(data)) {
      result = { ...result, ...data, items: Array.isArray(data.items) ? data.items : [] };
    }
    if (memoryCache.get(backtestCacheKey)?.stale) degraded.push("v20_backtest_cache_stale");
  } catch {
    degraded.push("v20_validation_summary");
  }
  const summary = Array.isArray(result.items) ? result.items : [];
  const generatedAt = summary.map((row) => row.generatedAt || row.generated_at).filter(Boolean).sort().at(-1) || null;
  const dataDates = summary.flatMap((row) => [
    row.firstDataDate || row.first_data_date,
    row.lastDataDate || row.last_data_date,
  ]).filter(Boolean).sort();
  const sampleCount = Math.max(0, Number(result.sampleCount) || 0);
  const minimumSampleCount = Math.max(1, Number(result.minimumSampleCount) || 100);
  return {
    ...publicMeta({
      dataState: result.sufficient && summary.length ? (degraded.length ? "partial" : "complete") : "partial",
      dataDate: dataDates.at(-1) || publication.publishedDataDate,
      sourceDates: { validation: dataDates.at(-1) || null },
      fetchedAt: generatedAt,
      completeness: Math.min(100, sampleCount / minimumSampleCount * 100),
      degraded,
      publication,
    }),
    model,
    horizon,
    validationType: "immutable_forward_observation",
    methodology: "point-in-time-snapshot-next-session-cost-and-benchmark-adjusted",
    noLookAhead: true,
    status: result.status,
    sufficient: result.sufficient === true,
    sampleCount,
    minimumSampleCount,
    topN: Number(result.topN) || topN,
    filters: { strategy: strategy || null, regime: regime || null, industry: industry || null, topN },
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
  encodeCursor,
  decodeCursor,
  publicMeta,
  pruneResolvedDegradedSources,
  normalizePublication,
  persistGlobalMarket,
  loadPublicationState,
  loadSignals,
  clearCache() { memoryCache.clear(); },
};
