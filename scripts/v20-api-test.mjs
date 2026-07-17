import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const originalFetch = globalThis.fetch;
const originalInternalKey = process.env.TWSS_V20_INTERNAL_KEY;
const originalMarketSecretKey = process.env.MARKET_SUPABASE_SECRET_KEY;
const originalMarketServiceKey = process.env.MARKET_SUPABASE_SERVICE_ROLE_KEY;
const originalSecretKey = process.env.SUPABASE_SECRET_KEY;
const originalServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
const originalPublishableKey = process.env.SUPABASE_PUBLISHABLE_KEY;
const originalFinnhubKey = process.env.FINNHUB_API_KEY;
const originalAlphaVantageKey = process.env.ALPHA_VANTAGE_API_KEY;
delete process.env.SUPABASE_SECRET_KEY;
delete process.env.MARKET_SUPABASE_SECRET_KEY;
delete process.env.MARKET_SUPABASE_SERVICE_ROLE_KEY;
process.env.SUPABASE_SERVICE_ROLE_KEY = "test-service-role-key";
process.env.SUPABASE_PUBLISHABLE_KEY = "test-public-key";
process.env.FINNHUB_API_KEY = "";
process.env.ALPHA_VANTAGE_API_KEY = "";
const calls = [];
let fugleEnabled = false;

const PUBLICATION_RUN_ID = 701;
const PUBLICATION_KEY = "a".repeat(64);
const CONTENT_HASH = "b".repeat(64);
const SIGNAL_GENERATED_AT = "2026-07-16T09:58:00Z";
const SIGNAL_UPDATED_AT = "2026-07-16T09:59:00Z";
const MARKET_CONTEXT_SNAPSHOT = {
  data_date: "2026-07-16",
  model_version: "20.1",
  regime: "sideways",
  regime_score: 4.25,
  confidence: 82,
  completeness: 87.5,
  status: "partial",
  taiex: { close: 23500, basis: "official" },
  tpex: { close: 275, basis: "official" },
  tx_futures: { settlement: 23280 },
  breadth: { all: { advanceRatio: 52.5 } },
  institutional: { net: 1200000 },
  global_context: { sp500: { value: 6300, dataDate: "2026-07-15" } },
  source_dates: { snapshots: "2026-07-16", global: "2026-07-15" },
  degraded_sources: ["tx_futures_delayed"],
  fetched_at: "2026-07-16T09:55:00Z",
  generated_at: "2026-07-16T09:56:00Z",
  updated_at: "2026-07-16T09:57:00Z",
};
const publicationHead = {
  audience: "public",
  run_id: PUBLICATION_RUN_ID,
  publication_key: PUBLICATION_KEY,
  content_hash: CONTENT_HASH,
  data_date: "2026-07-16",
  revision: 3,
  published_at: "2026-07-16T10:00:00Z",
  updated_at: "2026-07-16T10:00:00Z",
};
const recommendationRun = {
  id: PUBLICATION_RUN_ID,
  publication_key: PUBLICATION_KEY,
  content_hash: CONTENT_HASH,
  data_date: "2026-07-16",
  revision: 3,
  status: "published",
  model_version: "20.1",
  feature_version: "twss-v20.1-features",
  cost_model_version: "tw-market-cost-2026-07",
  calibration_version: null,
  source_manifest: {
    sourceDates: {
      universe: "2026-07-16",
      listed: "2026-07-16",
      otc: "2026-07-16",
      etf: "2026-07-16",
    },
  },
  market_context_snapshot: MARKET_CONTEXT_SNAPSHOT,
  expected_symbol_count: 3,
  scored_symbol_count: 3,
  cycle_completeness: 100,
  published_at: "2026-07-16T10:00:00Z",
};

const rankingRows = [1, 2, 3].map((rank) => ({
  run_id: PUBLICATION_RUN_ID,
  symbol: `233${rank - 1}`,
  name: `測試股票 ${rank}`,
  signal_date: "2026-07-16",
  model_key: "short",
  horizon_days: 5,
  model_version: "20.1",
  group_name: "listed",
  market: "上市",
  industry: "半導體業",
  strategy_key: "momentum_breakout",
  rank_position: rank,
  previous_rank: rank + 2,
  rank_delta: 2,
  market_percentile: 100 - rank,
  raw_opportunity_score: 94 - rank,
  net_opportunity_score: 88 - rank,
  risk_score: 20 + rank,
  confidence: 80,
  completeness: 100,
  estimated_commission_pct: 0.285,
  estimated_tax_pct: 0.3,
  estimated_slippage_pct: 0.18,
  estimated_spread_pct: 0.08,
  estimated_total_cost_pct: 0.845,
  downside_penalty_score: 2.5,
  turnover_penalty_score: 1.2,
  cost_penalty_score: 3.38,
  turnover_exposure: 1.4142,
  liquidity_grade: rank === 1 ? "A" : "B",
  opportunity_state: "成立",
  prediction_basis: rank === 1 ? "transparent-rule-ranking" : "walk-forward-calibration",
  calibrated_up_probability: rank === 3 ? 63 : rank === 2 ? 61 : 66,
  expected_return_net: rank === 3 ? 1.4 : 1.1,
  expected_excess_return_gross: rank === 3 ? 2.9 : 2.5,
  expected_excess_return_net: rank === 3 ? 2.1 : 1.7,
  calibration_sample_count: rank === 3 ? 120 : rank === 2 ? 60 : 0,
  benchmark_key: "TAIEX",
  is_eligible: true,
  public_visible: true,
  research_only: false,
  recommended_action: rank === 1 ? "可以布局" : "資料不足",
  feature_scores: {
    priceVolumeTrend: 82,
    institutional: 76,
    relativeIndustry: 74,
    volatilityRiskReward: 68,
    marketGlobal: 18,
    revenueEventCatalyst: 64,
    liquidityExecutionCost: 86,
  },
  gate_results: {
    data_complete: true,
    tradeable_liquid: true,
    market_allowed: true,
    trend_structure: true,
    relative_strength: true,
    evidence_support: true,
    positive_expectancy: true,
  },
  reasons: ["成本後機會值位於前段"],
  risks: ["跌破結構低點則失效"],
  invalidation_conditions: ["法人轉為連續賣超"],
  source_manifest: {
    sourceDates: { listed: "2026-07-16", price: "2026-07-16" },
    signalGeneratedAt: SIGNAL_GENERATED_AT,
    signalUpdatedAt: SIGNAL_UPDATED_AT,
  },
  input_hash: "c".repeat(64),
  recorded_at: "2026-07-16T10:00:00Z",
}));

const blendRows = rankingRows.map((row) => ({
  ...row,
  model_key: "medium",
  horizon_days: "blend",
  strategy_key: "medium_blend",
  component_horizons: {
    10: { rawOpportunityScore: row.raw_opportunity_score - 2, netOpportunityScore: row.net_opportunity_score - 2 },
    20: { rawOpportunityScore: row.raw_opportunity_score, netOpportunityScore: row.net_opportunity_score },
    40: { rawOpportunityScore: row.raw_opportunity_score + 2, netOpportunityScore: row.net_opportunity_score + 2 },
  },
  blend_weights: { 10: 0.25, 20: 0.5, 40: 0.25 },
}));

const detailSignalRow = {
  ...rankingRows[0],
  symbol: "2330",
  rank_position: null,
  market_percentile: null,
  is_eligible: false,
  gate_results: {
    data_complete: true,
    tradeable_liquid: true,
    market_allowed: true,
    trend_structure: false,
    relative_strength: false,
    evidence_support: true,
    positive_expectancy: true,
    probabilityBasis: "transparent-rule-ranking",
    quoteSnapshot: {
      tradeDate: "2026-07-16",
      close: 1000,
      change: 1.25,
      open: 990,
      high: 1010,
      low: 985,
      volume: 20000,
      value: 20000000,
      source: "stock_analysis_cache",
    },
  },
  feature_scores: {
    priceVolumeTrend: 82,
    institutional: 76,
    relativeIndustry: 74,
    volatilityRiskReward: 68,
    marketGlobal: 18,
    revenueEventCatalyst: 64,
    liquidityExecutionCost: 86,
  },
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
  if (url.hostname === "api.fugle.tw" && fugleEnabled) {
    assert.equal(init.headers["x-api-key"], "server-fugle-key");
    return Response.json({
      symbol: "5880", name: "合庫金", market: "TSE", date: "2026-07-17",
      lastPrice: 25.8, change: 0.3, changePercent: 1.1765,
      openPrice: 25.55, highPrice: 25.9, lowPrice: 25.45,
      total: { tradeVolume: 18000, tradeValue: 460000000 },
      isClose: true, lastUpdated: "2026-07-17T05:30:00Z",
    });
  }
  if (url.hostname !== "lfkdkdyaatdlizryiyon.supabase.co") {
    throw new Error(`unexpected external request: ${url.hostname}`);
  }
  if (url.pathname.endsWith("/v20_publication_head")) {
    return Response.json([publicationHead]);
  }
  if (url.pathname.endsWith("/v20_recommendation_runs")) {
    return Response.json([recommendationRun]);
  }
  if (url.pathname.endsWith("/v20_recommendation_items")) {
    const symbol = String(url.searchParams.get("symbol") || "").replace("eq.", "");
    if (symbol) {
      return Response.json(symbol === "2330" ? [detailSignalRow]
        : symbol === "2331" ? [rankingRows[1]]
        : symbol === "2333" ? [
          detailSignalRow,
          {
            ...detailSignalRow,
            horizon_days: 10,
            gate_results: {
              ...detailSignalRow.gate_results,
              quoteSnapshot: { ...detailSignalRow.gate_results.quoteSnapshot, close: 1001 },
            },
          },
        ] : []);
    }
    const after = Number(String(url.searchParams.get("rank_position") || "gt.0").replace("gt.", ""));
    const offset = Number(url.searchParams.get("offset") || 0);
    const limit = Number(url.searchParams.get("limit") || 10);
    const ordered = String(url.searchParams.get("order") || "").startsWith("risk_score.asc")
      ? [...rankingRows].sort((left, right) => left.risk_score - right.risk_score)
      : rankingRows;
    return Response.json(ordered
      .filter((row) => row.rank_position > after)
      .slice(offset, offset + limit));
  }
  if (url.pathname.endsWith("/rpc/twss_v20_read_validation_summary")) {
    return Response.json({
      status: "insufficient_data",
      source: "immutable_forward_observations",
      sampleCount: 0,
      minimumSampleCount: 100,
      sufficient: false,
      topN: 50,
      items: [],
    });
  }
  if (url.pathname.endsWith("/rpc/twss_v20_persist_global_context")) {
    return Response.json(true);
  }
  if (url.pathname.endsWith("/rpc/twss_v20_internal_provider_config")) {
    return Response.json({
      fugleConfigured: fugleEnabled,
      fugleMarketDataApiKey: fugleEnabled ? "server-fugle-key" : "",
    });
  }
  if (url.pathname.endsWith("/stock_snapshots")) {
    const symbol = String(url.searchParams.get("symbol") || "").replace("eq.", "");
    return Response.json(symbol === "5880" ? [{
      symbol: "5880", trade_date: "2026-07-16", close: 25.5, change_pct: 0.5917,
      volume: 17727, open: 25.2, high: 25.5, low: 25.15, trade_value: 450128521,
      market: "上市", industry: "金融保險業", instrument_type: "股票",
      source: "TWSE stored", source_dates: { price: "2026-07-16" },
      raw_data: { name: "合庫金" }, updated_at: "2026-07-16T10:00:00Z",
    }] : []);
  }
  if (url.pathname.endsWith("/v20_model_signals")) {
    const symbol = String(url.searchParams.get("symbol") || "").replace("eq.", "");
    return Response.json(symbol === "5880" ? [
      { ...detailSignalRow, run_id: null, symbol: "5880", name: "合庫金", model_version: "20.1", signal_date: "2026-07-16" },
      { ...detailSignalRow, run_id: null, symbol: "5880", name: "合庫金", model_key: "medium", horizon_days: 20, model_version: "20.1", signal_date: "2026-07-16" },
    ] : []);
  }
  if (url.pathname.endsWith("/rpc/twss_v20_read_medium_blend")) {
    const query = JSON.parse(init.body).p_query;
    const afterRank = Number(query.afterRank || 0);
    const limit = Number(query.limit || 10);
    const items = blendRows.filter((row) => row.rank_position > afterRank).slice(0, limit);
    return Response.json({
      run: { runId: PUBLICATION_RUN_ID, dataDate: "2026-07-16" },
      items,
      total: blendRows.length,
      pageCount: items.length,
      hasMore: afterRank + items.length < blendRows.length,
      nextAfterRank: items.at(-1)?.rank_position || null,
      blendWeights: { 10: 0.25, 20: 0.5, 40: 0.25 },
    });
  }
  throw new Error(`unexpected Supabase path: ${url.pathname}`);
};

const backend = await import(`../src/v20-backend.js?test=${Date.now()}`);
const rankingsRoute = (await import(`../api/v20/rankings.js?test=${Date.now()}`)).default;
const marketRoute = (await import(`../api/v20/market.js?test=${Date.now()}`)).default;
const stocksRoute = (await import(`../api/v20/stocks.js?test=${Date.now()}`)).default;
const backtestRoute = (await import(`../api/v20/backtest.js?test=${Date.now()}`)).default;
const shared = await import(`../api/v20/_shared.js?test=${Date.now()}`);

try {
  const parsed = backend.parseV20RankingQuery(new URLSearchParams({ model: "short" }));
  assert.equal(parsed.horizon, 5);
  assert.equal(parsed.sort, "net_opportunity_desc");
  assert.equal(parsed.afterRank, 0);
  assert.equal(parsed.offset, 0);
  assert.deepEqual(backend.v20BackendInternals.MODEL_HORIZONS, {
    short: [2, 3, 5, 10],
    medium: [10, 20, 40],
  });
  for (const horizon of [10, 20, 40]) {
    assert.equal(backend.parseV20RankingQuery(new URLSearchParams({ model: "medium", horizon })).horizon, horizon);
  }
  assert.equal(
    backend.parseV20RankingQuery(new URLSearchParams({ model: "medium", horizon: "blend" })).horizon,
    "blend",
  );
  assert.throws(
    () => backend.parseV20RankingQuery(new URLSearchParams({ model: "medium", horizon: "60" })),
    (error) => error?.code === "invalid_horizon",
    "60-day medium rows may remain for research but must not be public",
  );
  for (const sort of ["probability_desc", "expected_value_desc"]) {
    assert.throws(
      () => backend.parseV20RankingQuery(new URLSearchParams({ model: "short", sort })),
      (error) => error?.code === "invalid_sort",
      `${sort} must not be accepted before calibrated evidence exists`,
    );
  }

  const normalized = backend.v20BackendInternals.normalizeRanking(rankingRows[1]);
  assert.equal(normalized.forecasts["5"].upProbability, null);
  assert.equal(normalized.forecasts["5"].dataState, "insufficient_history");
  assert.equal(normalized.tradeDate, "2026-07-16",
    "an immutable price source date may be presented without inventing a quote");
  assert.equal(normalized.quote, null,
    "a source date alone must never be presented as an immutable close");
  assert.equal(normalized.analysisGeneratedAt, SIGNAL_GENERATED_AT);

  const updatedOnlyTimestamp = backend.v20BackendInternals.normalizeRanking({
    ...rankingRows[1],
    source_manifest: {
      ...rankingRows[1].source_manifest,
      signalGeneratedAt: null,
      signalUpdatedAt: SIGNAL_UPDATED_AT,
    },
  });
  assert.equal(updatedOnlyTimestamp.analysisGeneratedAt, SIGNAL_UPDATED_AT,
    "signalUpdatedAt is the honest fallback when the immutable item lacks signalGeneratedAt");

  const firstPublication = backend.v20BackendInternals.normalizePublication({
    ...recommendationRun,
    ...publicationHead,
  });
  const revisedPublication = backend.v20BackendInternals.normalizePublication({
    ...recommendationRun,
    ...publicationHead,
    id: PUBLICATION_RUN_ID + 1,
    run_id: PUBLICATION_RUN_ID + 1,
    publication_key: "d".repeat(64),
    content_hash: "e".repeat(64),
    revision: 4,
    market_context_snapshot: {
      ...MARKET_CONTEXT_SNAPSHOT,
      regime: "bear",
      regime_score: -35,
      updated_at: "2026-07-16T10:05:00Z",
    },
  });
  backend.v20BackendInternals.clearCache();
  calls.length = 0;
  const firstMarketSnapshot = await backend.readV20Market({ publication: firstPublication });
  const revisedMarketSnapshot = await backend.readV20Market({ publication: revisedPublication });
  assert.equal(firstMarketSnapshot.market.regimeKey, "sideways");
  assert.equal(revisedMarketSnapshot.market.regimeKey, "bear",
    "same-date publication revisions must not share the market cache entry");
  assert.ok(calls.every((call) => !call.url.pathname.endsWith("/v20_market_context")),
    "market reads must use the immutable context copied into the publication run");

  backend.v20BackendInternals.clearCache();
  calls.length = 0;
  await backend.readV20Stock("2330", { publication: firstPublication });
  await backend.readV20Stock("2330", { publication: revisedPublication });
  const revisionStockReads = calls.filter((call) =>
    call.url.pathname.endsWith("/v20_recommendation_items") &&
    call.url.searchParams.get("symbol") === "eq.2330");
  assert.deepEqual(
    revisionStockReads.map((call) => call.url.searchParams.get("run_id")),
    [`eq.${PUBLICATION_RUN_ID}`, `eq.${PUBLICATION_RUN_ID + 1}`],
    "same-date publication revisions must not share the stock cache entry",
  );
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
  assert.equal(bootstrap.rawOpportunityScore, detailSignalRow.raw_opportunity_score);
  assert.equal(bootstrap.netOpportunityScore, detailSignalRow.net_opportunity_score);
  assert.equal(bootstrap.opportunityScore, detailSignalRow.net_opportunity_score,
    "the public opportunity score must be the stored cost/risk-adjusted score");
  assert.equal(bootstrap.gatePassed, false,
    "an immutable non-eligible item must not inherit a legacy gate default");
  assert.deepEqual(bootstrap.executionCosts, {
    commissionPct: 0.285,
    taxPct: 0.3,
    slippagePct: 0.18,
    spreadPct: 0.08,
    totalPct: 0.845,
  });
  assert.deepEqual(bootstrap.penalties, {
    downside: 2.5,
    turnover: 1.2,
    cost: 3.38,
    turnoverExposure: 1.4142,
  });
  assert.equal(bootstrap.liquidityGrade, "A");
  assert.equal(bootstrap.calibrationSampleCount, 0);
  assert.deepEqual(bootstrap.quote, {
    tradeDate: "2026-07-16",
    close: 1000,
    change: 1.25,
    open: 990,
    high: 1010,
    low: 985,
    volume: 20000,
    value: 20000000,
    source: "stock_analysis_cache",
  });
  assert.equal(bootstrap.tradeDate, "2026-07-16");
  assert.equal(bootstrap.analysisGeneratedAt, SIGNAL_GENERATED_AT);
  assert.equal(bootstrap.tradePlan.stopLoss, 95);
  assert.equal(bootstrap.gateReasons.find((item) => item.key === "trend_structure")?.status, "fail");
  assert.equal(bootstrap.gateReasons.find((item) => item.key === "score_threshold")?.status, "pass");
  assert.equal(bootstrap.gateReasons.find((item) => item.key === "confidence_threshold")?.status, "pass");
  assert.equal(bootstrap.scoreExplanation.find((item) => item.key === "marketGlobal")?.weight, 10);
  assert.equal(bootstrap.marketImpact.featureKey, "marketGlobal");
  assert.equal(bootstrap.marketImpact.opportunityWeight, 10);
  assert.equal(bootstrap.marketImpact.opportunityDeltaFromNeutral, -3.2);

  const mediumExplanation = backend.v20BackendInternals.normalizeRanking({
    ...detailSignalRow,
    model_key: "medium",
    horizon_days: 40,
    feature_scores: {
      revenueProfitGrowth: 81,
      financialQuality: 74,
      mediumTrend: 79,
      institutionalPositioning: 68,
      industryEnvironment: 72,
      valuationReasonableness: 63,
      liquidityRisk: 84,
    },
  });
  assert.equal(mediumExplanation.scoreExplanation.find((item) => item.key === "industryEnvironment")?.weight, 10);
  assert.equal(mediumExplanation.marketImpact.featureKey, "industryEnvironment");
  assert.equal(mediumExplanation.marketImpact.opportunityWeight, 10);

  const calibrated = backend.v20BackendInternals.normalizeRanking({
    ...detailSignalRow,
    prediction_basis: "walk-forward-calibration",
    calibrated_up_probability: 63,
    expected_return_net: 1.4,
    expected_excess_return_gross: 2.9,
    expected_excess_return_net: 2.1,
    calibration_sample_count: 120,
    return_p10: -3,
    return_p50: 2,
    return_p90: 7,
    mfe: 8,
    mae: -4,
    target_first_probability: 59,
  });
  assert.equal(calibrated.predictionState.status, "calibrated");
  assert.equal(calibrated.forecasts["5"].upProbability, 63);
  assert.equal(calibrated.forecasts["5"].expectedNetReturn, 1.4);
  assert.equal(calibrated.forecasts["5"].expectedExcessReturnGross, 2.9);
  assert.equal(calibrated.forecasts["5"].expectedExcessReturnNet, 2.1);
  assert.equal(calibrated.forecasts["5"].averageMfe, 8);
  assert.equal(calibrated.expectedValue, 1.4);

  const excessOnly = backend.v20BackendInternals.normalizeRanking({
    ...detailSignalRow,
    prediction_basis: "walk-forward-calibration",
    calibration_sample_count: 120,
    expected_return_net: null,
    expected_excess_return_net: 2.1,
  });
  assert.equal(excessOnly.forecasts["5"].expectedNetReturn, null);
  assert.equal(excessOnly.forecasts["5"].expectedExcessReturnNet, 2.1);
  const returnOnly = backend.v20BackendInternals.normalizeRanking({
    ...detailSignalRow,
    prediction_basis: "walk-forward-calibration",
    calibration_sample_count: 120,
    expected_return_net: 1.4,
    expected_excess_return_net: null,
  });
  assert.equal(returnOnly.forecasts["5"].expectedNetReturn, 1.4);
  assert.equal(returnOnly.forecasts["5"].expectedExcessReturnNet, null);

  calls.length = 0;
  const privateSignals = await backend.v20BackendInternals.loadSignals("2330", {
    runId: PUBLICATION_RUN_ID,
    publishedDataDate: "2026-07-16",
  });
  assert.equal(privateSignals.length, 1,
    "server-side detail reads must include a non-eligible immutable item");
  const privateRead = calls.find((call) => call.url.pathname.endsWith("/v20_recommendation_items"));
  assert.equal(privateRead.init.headers.apikey, "test-service-role-key");
  assert.equal(privateRead.init.headers.authorization, "Bearer test-service-role-key");
  assert.equal(privateRead.url.searchParams.get("run_id"), `eq.${PUBLICATION_RUN_ID}`);
  assert.equal(privateRead.url.searchParams.get("symbol"), "eq.2330");
  assert.equal(privateRead.url.searchParams.get("public_visible"), "eq.true");
  assert.equal(privateRead.url.searchParams.get("research_only"), "eq.false");

  calls.length = 0;
  const missingSignals = await backend.v20BackendInternals.loadSignals("2332", {
    runId: PUBLICATION_RUN_ID,
    publishedDataDate: "2026-07-16",
  });
  assert.deepEqual(missingSignals, []);
  assert.ok(calls.every((call) => call.url.pathname.endsWith("/v20_recommendation_items")),
    "an empty immutable item read must not fall back to a raw table or browser RPC");

  const oldImmutableStock = await backend.readV20Stock("2331", { publication: firstPublication });
  assert.equal(oldImmutableStock.tradeDate, "2026-07-16",
    "an old immutable item may still disclose its verified price source date");
  assert.equal(oldImmutableStock.quote, null,
    "an old immutable item without quoteSnapshot must remain honest about its missing close");
  assert.equal(oldImmutableStock.analysisGeneratedAt, SIGNAL_GENERATED_AT);

  const conflictingImmutableStock = await backend.readV20Stock("2333", { publication: firstPublication });
  assert.equal(conflictingImmutableStock.quote, null,
    "conflicting immutable horizon quotes must fail closed instead of choosing one");
  assert.ok(conflictingImmutableStock.degradedSources.includes("immutable_quote_conflict"));

  fugleEnabled = true;
  backend.v20BackendInternals.clearCache();
  const outsidePublicationStock = await backend.readV20Stock("5880", { publication: firstPublication });
  assert.equal(outsidePublicationStock.dataState, "partial");
  assert.equal(outsidePublicationStock.stock.name, "合庫金");
  assert.equal(outsidePublicationStock.quote.tradeDate, "2026-07-17");
  assert.equal(outsidePublicationStock.quote.source, "Fugle MarketData");
  assert.equal(outsidePublicationStock.quoteState.independentFromModelPublication, true);
  assert.equal(outsidePublicationStock.publicationCoverage.member, false);
  assert.equal(outsidePublicationStock.publicationCoverage.status, "outside_current_publication");
  assert.equal(outsidePublicationStock.publicationCoverage.referenceModelVersion, "20.1");
  assert.equal(outsidePublicationStock.modelStates.short.status, "outside_publication");
  assert.equal(outsidePublicationStock.short[0].referenceOnly, true);
  assert.ok(outsidePublicationStock.degradedSources.includes("outside_current_publication"));
  fugleEnabled = false;
  backend.v20BackendInternals.clearCache();

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
  assert.equal(stockDetail.runId, PUBLICATION_RUN_ID);
  assert.equal(stockDetail.stock.runId, PUBLICATION_RUN_ID);
  assert.equal(stockDetail.tradeDate, "2026-07-16");
  assert.equal(stockDetail.analysisGeneratedAt, SIGNAL_GENERATED_AT);
  assert.deepEqual(stockDetail.quote, bootstrap.quote,
    "the stock API must expose only the quote copied into the immutable recommendation item");
  assert.equal(stockDetail.analysis, null);
  assert.deepEqual(stockDetail.news, []);
  assert.deepEqual(stockDetail.relatedStocks, []);
  assert.equal(stockDetail.newsState.status, "not_recorded_in_publication");
  assert.equal(stockDetail.legacyReference, null);
  const stockHeadRead = calls.find((call) => call.url.pathname.endsWith("/v20_publication_head"));
  const stockRunRead = calls.find((call) => call.url.pathname.endsWith("/v20_recommendation_runs"));
  const stockItemRead = calls.find((call) => call.url.pathname.endsWith("/v20_recommendation_items"));
  assert.ok(stockHeadRead, "stock API must resolve the immutable publication head");
  assert.ok(stockRunRead, "stock API must resolve the immutable published run");
  assert.ok(stockItemRead);
  assert.equal(stockItemRead.url.searchParams.get("run_id"), `eq.${PUBLICATION_RUN_ID}`);
  assert.equal(stockItemRead.init.headers.apikey, "test-service-role-key");
  assert.ok(calls.every((call) => ![
    "/stock_sync_state",
    "/v20_model_signals",
    "/v20_ranking_snapshots",
    "/rpc/twss_v20_public_stock_signals",
  ].some((suffix) => call.url.pathname.endsWith(suffix))),
  "stock API must not read mutable staging tables or a browser-facing RPC");

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
  assert.equal(first.runId, PUBLICATION_RUN_ID);
  assert.equal(first.publicationKey, PUBLICATION_KEY);
  assert.equal(first.contentHash, CONTENT_HASH);
  assert.equal(first.publicationPhase, "complete");
  assert.equal(first.enrichmentPending, 0);
  assert.equal(first.dataCompleteness, 100);
  assert.equal(first.sort, "net_opportunity_desc");
  assert.deepEqual(first.scoreSemantics.opportunityScore, {
    deprecated: true,
    aliasOf: "netOpportunityScore",
  });
  assert.deepEqual(first.items.map((row) => row.netOpportunityScore), [87, 86]);
  assert.equal(first.items[0].rawOpportunityScore, 93);
  assert.deepEqual(first.items[0].executionCosts, {
    commissionPct: 0.285,
    taxPct: 0.3,
    slippagePct: 0.18,
    spreadPct: 0.08,
    totalPct: 0.845,
  });
  assert.equal(first.items[0].penalties.downside, 2.5);
  assert.equal(first.items[0].penalties.turnover, 1.2);
  assert.equal(first.items[0].liquidityGrade, "A");
  assert.equal(first.items[0].calibrationSampleCount, 0);
  assert.equal(first.items[0].forecasts["5"].upProbability, null);
  assert.equal(first.items[1].calibrationSampleCount, 60);
  assert.equal(first.items[1].forecasts["5"].upProbability, null,
    "a Walk-forward label without 100 samples must not expose probability");
  const pageCall = calls.find((call) => call.url.pathname.endsWith("/v20_recommendation_items"));
  assert.ok(pageCall, "ranking reads must query immutable recommendation items");
  assert.equal(pageCall.url.searchParams.get("run_id"), `eq.${PUBLICATION_RUN_ID}`);
  assert.equal(pageCall.url.searchParams.has("ranking_date"), false);
  assert.equal(pageCall.url.searchParams.get("order"), "rank_position.asc,symbol.asc",
    "immutable ranks provide stable keyset ordering for the default net-opportunity sort");
  assert.equal(pageCall.url.searchParams.has("offset"), false);
  assert.equal(pageCall.init.headers?.Prefer, undefined, "page reads must not request exact counts");
  assert.equal(pageCall.init.headers.apikey, "test-service-role-key");
  assert.equal(pageCall.init.headers.authorization, "Bearer test-service-role-key");
  assert.ok(calls.every((call) => ![
    "/stock_sync_state",
    "/v20_model_signals",
    "/v20_ranking_snapshots",
  ].some((suffix) => call.url.pathname.endsWith(suffix))),
  "ranking API must not read legacy publication state or mutable staging tables");
  assert.ok(calls.every((call) => !call.url.pathname.includes("/rpc/twss_v20_public_")),
    "ranking API must not call browser-facing v20 RPCs");

  backend.v20BackendInternals.clearCache();
  calls.length = 0;
  const secondResponse = await rankingsRoute.fetch(new Request(
    `https://app.test/api/v20/rankings?model=short&horizon=5&limit=2&cursor=${encodeURIComponent(first.nextCursor)}`,
  ));
  assert.equal(secondResponse.status, 200);
  const second = await secondResponse.json();
  assert.deepEqual(second.items.map((row) => row.rank), [3]);
  assert.equal(second.items[0].calibrationSampleCount, 120);
  assert.equal(second.items[0].forecasts["5"].upProbability, 63);
  assert.equal(second.items[0].forecasts["5"].expectedNetReturn, 1.4);
  assert.equal(second.items[0].forecasts["5"].expectedExcessReturnNet, 2.1);
  const secondPageCall = calls.find((call) => call.url.pathname.endsWith("/v20_recommendation_items"));
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
  const riskPageCall = calls.find((call) => call.url.pathname.endsWith("/v20_recommendation_items"));
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
  const filteredPageCall = calls.find((call) => call.url.pathname.endsWith("/v20_recommendation_items"));
  assert.equal(filteredPageCall.url.searchParams.get("run_id"), `eq.${PUBLICATION_RUN_ID}`);
  assert.equal(filteredPageCall.url.searchParams.has("ranking_date"), false);
  assert.equal(filteredPageCall.url.searchParams.get("industry"), "eq.半導體業");
  assert.equal(filteredPageCall.url.searchParams.get("strategy_key"), "eq.momentum_breakout");
  assert.ok(filteredPageCall.url.searchParams.has("or"));

  backend.v20BackendInternals.clearCache();
  calls.length = 0;
  const rawScoreResponse = await rankingsRoute.fetch(new Request(
    "https://app.test/api/v20/rankings?model=short&horizon=5&sort=score_desc",
  ));
  assert.equal(rawScoreResponse.status, 200);
  const rawScoreCall = calls.find((call) => call.url.pathname.endsWith("/v20_recommendation_items"));
  assert.equal(
    rawScoreCall.url.searchParams.get("order"),
    "raw_opportunity_score.desc.nullslast,net_opportunity_score.desc.nullslast,symbol.asc",
    "score_desc must sort the unadjusted opportunity score",
  );

  backend.v20BackendInternals.clearCache();
  calls.length = 0;
  const blendFirstResponse = await rankingsRoute.fetch(new Request(
    "https://app.test/api/v20/rankings?model=medium&horizon=blend&limit=2",
  ));
  assert.equal(blendFirstResponse.status, 200);
  const blendFirst = await blendFirstResponse.json();
  assert.equal(blendFirst.horizon, "blend");
  assert.deepEqual(blendFirst.items.map((row) => row.rank), [1, 2]);
  assert.ok(blendFirst.nextCursor);
  assert.equal(blendFirst.items.every((row) => row.gatePassed && row.official), true);
  const blendRpcCall = calls.find((call) => call.url.pathname.endsWith("/rpc/twss_v20_read_medium_blend"));
  assert.deepEqual(JSON.parse(blendRpcCall.init.body).p_query, {
    runId: PUBLICATION_RUN_ID,
    groupName: null,
    industry: null,
    afterRank: 0,
    limit: 2,
  });
  backend.v20BackendInternals.clearCache();
  calls.length = 0;
  const blendNextResponse = await rankingsRoute.fetch(new Request(
    `https://app.test/api/v20/rankings?model=medium&horizon=blend&limit=2&cursor=${encodeURIComponent(blendFirst.nextCursor)}`,
  ));
  assert.equal(blendNextResponse.status, 200);
  assert.deepEqual((await blendNextResponse.json()).items.map((row) => row.rank), [3]);
  const blendNextCall = calls.find((call) => call.url.pathname.endsWith("/rpc/twss_v20_read_medium_blend"));
  assert.equal(JSON.parse(blendNextCall.init.body).p_query.afterRank, 2);

  backend.v20BackendInternals.clearCache();
  calls.length = 0;
  const home = await backend.readV20Home();
  assert.equal(home.dataDate, "2026-07-16");
  assert.equal(home.publicationPhase, "complete");
  assert.equal(home.runId, PUBLICATION_RUN_ID);
  assert.equal(home.dailyReport.dataDate, home.dataDate,
    "the base daily report must switch with the same atomic publication date");
  assert.equal(home.dailyReport.title, "每日市場摘要");
  assert.equal(home.dailyReport.source, "v20-deterministic-market-summary");
  assert.equal(home.dailyReport.generationMethod, "deterministic_rules");
  assert.equal(home.dailyReport.aiGenerated, false);
  assert.equal(home.dailyReport.publicationSemantics, "immutable_revision");
  assert.equal(home.dailyReport.cachedFallback, false);
  assert.equal(home.mediumTop.every((row) => row.horizon === "blend"), true);
  assert.deepEqual(home.mediumTop[0].blendWeights, { 10: 0.25, 20: 0.5, 40: 0.25 });
  assert.deepEqual(Object.keys(home.mediumTop[0].componentHorizons), ["10", "20", "40"]);
  assert.doesNotMatch(
    home.dailyReport.report.mainRisks[0].explanation,
    /分數與排序可能同日再次更新/,
    "an immutable publication must only change by publishing a traceable revision",
  );
  assert.ok(home.dailyReport.report.oneLine);
  assert.deepEqual(home.importantNews, []);
  assert.equal(home.importantNewsState.status, "not_recorded_in_publication");
  assert.deepEqual(home.dailyReport.report.importantNewsAndAnnouncements, []);
  assert.equal(Object.hasOwn(home, "fastestRisers"), false,
    "v20 must not expose mutable v19 risers inside an immutable publication");
  assert.equal(Object.hasOwn(home, "updateJobs"), false,
    "v20 public home must not expose legacy operational job status");
  assert.ok(calls.every((call) => !call.url.pathname.endsWith("/stock_sync_state")),
    "home publication resolution must never fall back to mutable worker state");

  backend.v20BackendInternals.clearCache();
  calls.length = 0;
  const backtestResponse = await backtestRoute.fetch(new Request(
    "https://app.test/api/v20/backtest?model=short&horizon=5",
  ));
  assert.equal(backtestResponse.status, 200);
  const backtest = await backtestResponse.json();
  assert.equal(backtest.validationType, "immutable_forward_observation");
  assert.equal(backtest.status, "insufficient_data");
  assert.equal(backtest.sufficient, false);
  assert.deepEqual(backtest.summary, []);
  const validationCall = calls.find((call) =>
    call.url.pathname.endsWith("/rpc/twss_v20_read_validation_summary"));
  assert.ok(validationCall, "validation API must use the service-only immutable outcome read model");
  assert.equal(validationCall.init.headers.apikey, "test-service-role-key");
  assert.equal(validationCall.init.headers.authorization, "Bearer test-service-role-key");
  assert.deepEqual(JSON.parse(validationCall.init.body).p_query, {
    modelKey: "short",
    horizonDays: 5,
    modelVersion: "20.1",
    strategyKey: null,
    marketRegime: null,
    industry: null,
    topN: 50,
    minimumSampleCount: 100,
  });
  assert.ok(calls.every((call) => !call.url.pathname.includes("/rpc/twss_v20_public_")),
    "validation API must not call the legacy public backtest RPC");

  backend.v20BackendInternals.clearCache();
  calls.length = 0;
  const staleCursor = backend.v20BackendInternals.encodeCursor(2, {
    ...parsed,
    rankingDate: "2026-07-16",
    publicationKey: "d".repeat(64),
  }, 2);
  const staleResponse = await rankingsRoute.fetch(new Request(
    `https://app.test/api/v20/rankings?model=short&cursor=${encodeURIComponent(staleCursor)}`,
  ));
  assert.equal(staleResponse.status, 400);
  assert.equal((await staleResponse.json()).error.code, "stale_ranking_cursor");
  assert.ok(calls.every((call) => !call.url.pathname.endsWith("/v20_recommendation_items")),
    "a stale cursor must be rejected before querying recommendation items");

  for (const rejectedSort of ["probability_desc", "expected_value_desc"]) {
    calls.length = 0;
    const rejectedSortResponse = await rankingsRoute.fetch(new Request(
      `https://app.test/api/v20/rankings?model=short&sort=${rejectedSort}`,
    ));
    assert.equal(rejectedSortResponse.status, 400);
    assert.equal((await rejectedSortResponse.json()).error.code, "invalid_sort");
    assert.ok(calls.every((call) => !call.url.pathname.endsWith("/v20_recommendation_items")),
      `${rejectedSort} must be rejected before querying immutable items`);
  }

  process.env.TWSS_V20_INTERNAL_KEY = "server-only-test-key";
  backend.v20BackendInternals.clearCache();
  calls.length = 0;
  const refreshGet = await marketRoute.fetch(new Request("https://app.test/api/v20/market?refresh=global"));
  assert.equal(refreshGet.status, 405, "global refresh must not mutate state through GET");
  assert.equal(refreshGet.headers.get("allow"), "POST, OPTIONS");
  assert.equal(calls.length, 0, "a rejected refresh method must not read data or call providers");

  const forbiddenRefresh = await marketRoute.fetch(new Request(
    "https://app.test/api/v20/market?refresh=global",
    { method: "POST", headers: { "x-twss-internal-key": "wrong-key" } },
  ));
  assert.equal(forbiddenRefresh.status, 403);
  assert.equal((await forbiddenRefresh.json()).error.code, "refresh_forbidden");
  assert.equal(calls.length, 0, "an invalid internal secret must fail before any backend/provider work");

  const preflight = await marketRoute.fetch(new Request(
    "https://app.test/api/v20/market?refresh=global",
    { method: "OPTIONS" },
  ));
  assert.equal(preflight.status, 204);
  assert.equal(preflight.headers.get("access-control-allow-methods"), "POST, OPTIONS");
  assert.match(preflight.headers.get("access-control-allow-headers") || "", /x-twss-internal-key/);

  const market = await marketRoute.fetch(new Request(
    "https://app.test/api/v20/market?refresh=global",
    { method: "POST", headers: { "x-twss-internal-key": "server-only-test-key" } },
  ));
  assert.equal(market.status, 200);
  const marketPayload = await market.json();
  assert.equal(marketPayload.runId, PUBLICATION_RUN_ID);
  assert.equal(marketPayload.market.regimeKey, "sideways");
  assert.deepEqual(marketPayload.globalRefresh, {
    attempted: true,
    persisted: true,
    availableOnNextPublication: true,
  });
  const persistenceCall = calls.find((call) =>
    call.url.pathname.endsWith("/rpc/twss_v20_persist_global_context"));
  assert.ok(persistenceCall, "an authorized refresh must persist through the service-only RPC");
  assert.equal(persistenceCall.init.method, "POST");
  assert.equal(persistenceCall.init.headers.apikey, "test-service-role-key");
  assert.equal(persistenceCall.init.headers.authorization, "Bearer test-service-role-key");
  assert.equal(JSON.parse(persistenceCall.init.body).p_token, "server-only-test-key");
  assert.ok(calls.every((call) => !call.url.pathname.endsWith("/v20_market_context")),
    "the market API must not mix a mutable context row into an immutable publication response");
  assert.ok(calls.every((call) => call.url.hostname === "lfkdkdyaatdlizryiyon.supabase.co"));

  const method = await shared.handleV20(new Request("https://app.test/api/v20/home", { method: "POST" }), async () => ({}));
  assert.equal(method.status, 405);

  // A Vercel deployment can legitimately have only the public Supabase key.
  // In that mode every public v20 read must stay available through the
  // bounded immutable RPCs, without silently restoring mutable table reads.
  delete process.env.SUPABASE_SECRET_KEY;
  delete process.env.SUPABASE_SERVICE_ROLE_KEY;
  delete process.env.MARKET_SUPABASE_SECRET_KEY;
  delete process.env.MARKET_SUPABASE_SERVICE_ROLE_KEY;
  const publicCalls = [];
  const publicPublication = {
    publicationPhase: "complete",
    publishedDataDate: "2026-07-16",
    publishedAt: "2026-07-16T10:00:00Z",
    runId: PUBLICATION_RUN_ID,
    publicationKey: PUBLICATION_KEY,
    contentHash: CONTENT_HASH,
    revision: 3,
    modelVersion: "20.1",
    featureVersion: "twss-v20.1-features",
    costModelVersion: "tw-market-cost-2026-07",
    calibrationVersion: null,
    sourceManifest: recommendationRun.source_manifest,
    marketContext: MARKET_CONTEXT_SNAPSHOT,
    expectedSymbolCount: 3,
    scoredSymbolCount: 3,
    dataCompleteness: 100,
  };
  const publicRun = {
    runId: PUBLICATION_RUN_ID,
    dataDate: "2026-07-16",
    revision: 3,
    modelVersion: "20.1",
    featureVersion: "twss-v20.1-features",
    costModelVersion: "tw-market-cost-2026-07",
    calibrationVersion: null,
    contentHash: CONTENT_HASH,
    marketRegime: "sideways",
    publishedAt: "2026-07-16T10:00:00Z",
  };
  const publicRpcItem = (row, overrides = {}) => ({
    symbol: row.symbol,
    name: row.name,
    signalDate: row.signal_date,
    modelKey: row.model_key,
    horizonDays: row.horizon_days,
    modelVersion: row.model_version,
    groupName: row.group_name,
    market: row.market,
    industry: row.industry,
    instrumentType: row.instrument_type,
    strategyKey: row.strategy_key,
    isEligible: row.is_eligible,
    rankPosition: row.rank_position,
    previousRank: row.previous_rank,
    rankDelta: row.rank_delta,
    marketPercentile: row.market_percentile,
    rawOpportunityScore: row.raw_opportunity_score,
    netOpportunityScore: row.net_opportunity_score,
    riskScore: row.risk_score,
    confidence: row.confidence,
    completeness: row.completeness,
    estimatedCommissionPct: row.estimated_commission_pct,
    estimatedTaxPct: row.estimated_tax_pct,
    estimatedSlippagePct: row.estimated_slippage_pct,
    estimatedSpreadPct: row.estimated_spread_pct,
    estimatedTotalCostPct: row.estimated_total_cost_pct,
    downsidePenaltyScore: row.downside_penalty_score,
    turnoverPenaltyScore: row.turnover_penalty_score,
    costPenaltyScore: row.cost_penalty_score,
    turnoverExposure: row.turnover_exposure,
    liquidityGrade: row.liquidity_grade,
    opportunityState: row.opportunity_state,
    predictionBasis: row.prediction_basis,
    calibratedUpProbability: row.calibrated_up_probability,
    expectedNetReturn: row.expected_return_net,
    expectedExcessReturnGross: row.expected_excess_return_gross,
    expectedExcessReturnNet: row.expected_excess_return_net,
    calibrationSampleCount: row.calibration_sample_count,
    benchmarkKey: row.benchmark_key,
    recommendedHoldingDays: row.recommended_holding_days,
    recommendedAction: row.recommended_action,
    entryLow: row.entry_low,
    entryHigh: row.entry_high,
    stopLoss: row.stop_loss,
    takeProfit1: row.take_profit_1,
    takeProfit2: row.take_profit_2,
    riskRewardRatio: row.risk_reward_ratio,
    featureScores: row.feature_scores,
    gateResults: row.gate_results,
    reasons: row.reasons,
    risks: row.risks,
    invalidationConditions: row.invalidation_conditions,
    sourceManifest: row.source_manifest,
    inputHash: row.input_hash,
    ...overrides,
  });
  const publicShortItem = publicRpcItem(detailSignalRow);
  const publicMediumItem = publicRpcItem(detailSignalRow, {
    modelKey: "medium",
    horizonDays: 40,
    rankPosition: 1,
    isEligible: true,
  });
  const researchOnly60DayItem = publicRpcItem(detailSignalRow, {
    modelKey: "medium",
    horizonDays: 60,
    rankPosition: 2,
    isEligible: true,
  });

  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(String(input));
    publicCalls.push({ url, init });
    if (url.hostname !== "lfkdkdyaatdlizryiyon.supabase.co") {
      throw new Error(`unexpected public fallback request: ${url}`);
    }
    if (url.pathname.endsWith("/rpc/twss_v20_read_publication_state")) {
      return Response.json(publicPublication);
    }
    if (url.pathname.endsWith("/rpc/twss_v20_read_rankings")) {
      return Response.json({
        run: publicRun,
        items: [publicMediumItem, researchOnly60DayItem],
        total: 2,
        pageCount: 2,
        hasMore: false,
        nextAfterRank: 2,
      });
    }
    if (url.pathname.endsWith("/rpc/twss_v20_read_stock_snapshot")) {
      const symbol = JSON.parse(init.body).p_query.symbol;
      return Response.json({
        run: publicRun,
        symbol,
        found: symbol === "2330",
        items: symbol === "2330" ? [publicShortItem, publicMediumItem, researchOnly60DayItem] : [],
      });
    }
    if (url.pathname.endsWith("/rpc/twss_v20_public_stock_reference")) {
      const symbol = JSON.parse(init.body).p_symbol;
      return Response.json(symbol === "5880" ? {
        snapshot: {
          stock: { symbol, name: "合庫金", market: "上市", priceDate: "2026-07-16", close: 25.5 },
          quote: { tradeDate: "2026-07-16", close: 25.5, change: 0.59, source: "stored market snapshot" },
          sourceDates: { price: "2026-07-16" },
          fetchedAt: "2026-07-16T10:00:00Z",
        },
        signals: [
          { ...detailSignalRow, symbol, name: "合庫金", model_version: "20.1", signal_date: "2026-07-16", outside_publication: true, reference_only: true },
          { ...detailSignalRow, symbol, name: "合庫金", model_key: "medium", horizon_days: 20, model_version: "20.1", signal_date: "2026-07-16", outside_publication: true, reference_only: true },
        ],
      } : { snapshot: {}, signals: [] });
    }
    if (url.pathname.endsWith("/rpc/twss_v20_read_validation_summary")) {
      return Response.json({
        status: "insufficient_data",
        source: "immutable_forward_observations",
        sampleCount: 0,
        minimumSampleCount: 100,
        sufficient: false,
        topN: 50,
        items: [],
      });
    }
    throw new Error(`unexpected public Supabase path: ${url.pathname}`);
  };

  const publicBackend = await import(`../src/v20-backend.js?public-rpc=${Date.now()}`);
  const publicState = await publicBackend.v20BackendInternals.loadPublicationState();
  assert.equal(publicState.runId, PUBLICATION_RUN_ID);
  assert.deepEqual(publicState.marketContext, MARKET_CONTEXT_SNAPSHOT);

  const publicRankings = await publicBackend.readV20Rankings(new URL(
    "https://app.test/api/v20/rankings?model=medium&horizon=40&limit=10",
  ));
  assert.deepEqual(publicRankings.items.map((row) => row.horizon), [40]);
  assert.equal(publicRankings.items[0].opportunityScore, detailSignalRow.net_opportunity_score);

  const publicStock = await publicBackend.readV20Stock("2330");
  assert.deepEqual(publicStock.short.map((row) => row.horizon), [5]);
  assert.deepEqual(publicStock.medium.map((row) => row.horizon), [40],
    "the research-only 60-day horizon must not escape through the public stock fallback");
  assert.equal(publicStock.tradeDate, "2026-07-16");
  assert.equal(publicStock.analysisGeneratedAt, SIGNAL_GENERATED_AT);
  assert.deepEqual(publicStock.quote, bootstrap.quote,
    "the bounded public RPC must preserve the immutable quote snapshot");

  const publicReferenceStock = await publicBackend.readV20Stock("5880");
  assert.equal(publicReferenceStock.dataState, "partial");
  assert.equal(publicReferenceStock.publicationCoverage.status, "outside_current_publication");
  assert.equal(publicReferenceStock.publicationCoverage.referenceSignalsUsed, true);
  assert.equal(publicReferenceStock.quote.close, 25.5);
  assert.equal(publicReferenceStock.short[0].legacyReference, true);

  const publicBacktest = await publicBackend.readV20Backtest(new URL(
    "https://app.test/api/v20/backtest?model=short&horizon=5",
  ));
  assert.equal(publicBacktest.status, "insufficient_data");
  assert.equal(publicBacktest.runId, PUBLICATION_RUN_ID);

  const publicRpcPaths = publicCalls.map((call) => call.url.pathname);
  for (const rpc of [
    "/rpc/twss_v20_read_publication_state",
    "/rpc/twss_v20_read_rankings",
    "/rpc/twss_v20_read_stock_snapshot",
    "/rpc/twss_v20_read_validation_summary",
    "/rpc/twss_v20_public_stock_reference",
  ]) {
    assert.ok(publicRpcPaths.some((path) => path.endsWith(rpc)), `missing public fallback ${rpc}`);
  }
  for (const call of publicCalls) {
    assert.equal(call.init.method, "POST");
    assert.equal(call.init.headers.apikey, "test-public-key");
    assert.equal(call.init.headers.authorization, undefined,
      "a public Supabase key must never be copied into an Authorization header");
    assert.ok(call.url.pathname.includes("/rpc/twss_v20_read_")
      || call.url.pathname.endsWith("/rpc/twss_v20_public_stock_reference"),
      "public fallback must use bounded read RPCs instead of direct tables");
  }
  const publicRankingCall = publicCalls.find((call) =>
    call.url.pathname.endsWith("/rpc/twss_v20_read_rankings"));
  assert.deepEqual(JSON.parse(publicRankingCall.init.body).p_query, {
    modelKey: "medium",
    horizonDays: 40,
    runId: PUBLICATION_RUN_ID,
    groupName: null,
    industry: null,
    afterRank: 0,
    limit: 10,
  });
  assert.ok(publicCalls.every((call) => JSON.parse(call.init.body || "{}").p_query?.horizonDays !== 60),
    "the server must never request the research-only 60-day horizon through a public RPC");

  const [html, ui, smart, sw, manifest, generator, backendSource, referenceMigration] = await Promise.all([
    readFile(new URL("../public/index.html", import.meta.url), "utf8"),
    readFile(new URL("../public/v20.js", import.meta.url), "utf8"),
    readFile(new URL("../public/smart.js", import.meta.url), "utf8"),
    readFile(new URL("../public/sw.js", import.meta.url), "utf8"),
    readFile(new URL("../public/manifest.webmanifest", import.meta.url), "utf8"),
    readFile(new URL("./generate-worker.mjs", import.meta.url), "utf8"),
    readFile(new URL("../src/v20-backend.js", import.meta.url), "utf8"),
    readFile(new URL("../supabase/migrations/20260717193000_public_stock_reference_fallback.sql", import.meta.url), "utf8"),
  ]);
  assert.match(referenceMigration,
    /revoke all on function public\.twss_v20_public_stock_reference\(text\)[\s\S]*grant execute[\s\S]*to anon, authenticated, service_role;/,
    "the bounded single-stock reference RPC must have an explicit public grant");
  assert.match(referenceMigration, /- 'up_probability'[\s\S]*- 'target_first_probability'/,
    "uncalibrated prediction fields must not escape through the reference RPC");
  for (const tab of ["home", "short", "medium", "watchlist", "validation"]) {
    assert.match(html, new RegExp(`data-tab="${tab}"`));
  }
  assert.doesNotMatch(html, /data-tab="(?:prediction|journal|portfolio)"/i);
  assert.match(ui, /載入更多新聞與公告/);
  assert.doesNotMatch(ui, /twss-v19-daily-report-cache/,
    "the v20 shell must not read or write the mutable v19 report cache");
  assert.doesNotMatch(ui, /\/data\/daily-report\.json/,
    "the v20 shell must not fall back to a mutable static report");
  assert.match(ui, /payload\.dailyReport/);
  assert.match(ui, /samePublication\(atomicReport\.meta, payload\)/,
    "the UI must bind its report to the exact recommendation run, key and content hash");
  assert.match(ui, /DAILY MARKET SUMMARY/);
  assert.match(ui, /每日市場摘要/);
  assert.doesNotMatch(ui, /AI 每日報告|DAILY AI BRIEF/,
    "the deterministic summary must not be presented as AI-generated");
  assert.doesNotMatch(ui, /twssV19Benchmarks|officialIndices/,
    "v20 market cards must use only the run's market_context_snapshot");
  assert.match(ui, /const qualityState = payload\?\.dataState/,
    "data quality must come from dataState instead of publication completion");
  assert.doesNotMatch(ui, /dataState: visibleDegraded\.length \? home\.dataState : 'complete'/,
    "the browser must never upgrade backend partial or error data to complete");
  const dailySectionStart = ui.indexOf("function dailyReportSection()");
  const dailySectionEnd = ui.indexOf("function homePageV20()", dailySectionStart);
  assert.ok(dailySectionStart >= 0 && dailySectionEnd > dailySectionStart);
  assert.doesNotMatch(ui.slice(dailySectionStart, dailySectionEnd), /statusBanner\(/,
    "the daily summary must not repeat the page's primary data-status banner");
  assert.match(ui, /dateKey\(first\(value\?\.dataDate, value\?\.date\)\) === expectedDate/,
    "a degraded source may resolve only when its value belongs to the publication date");
  assert.match(ui, /marketChangePercent[\s\S]*first\(value\?\.changePercent, value\?\.change_pct\)/);
  assert.match(ui, /marketChangePoints[\s\S]*value\?\.change[\s\S]*\} 點/,
    "point changes must be labelled as points rather than percentages");
  assert.match(ui, /範圍 -100～\+100/);
  assert.match(ui, /price: \{ twse: listed, tpex: otc, common: aligned \? listed : '', aligned \}/,
    "v20 home source dates must populate the canonical listed/OTC header shape");
  assert.match(ui, /S\.date = payload\.dataDate \|\| S\.date;\s*applyHomeSourceDates\(payload\);\s*S\.mode[\s\S]*updateMarketHeader\(\);/,
    "official source dates must be written before the market header is rendered");
  assert.doesNotMatch(ui, /個來源待補/,
    "the UI must not count individual missing indicators as independent data sources");
  assert.match(ui, /此批次未保存收盤價/,
    "stock details must disclose when the immutable recommendation has no quote snapshot");
  assert.doesNotMatch(ui, /quoteClose\s*=\s*first\([^;]*(?:stock\?\.close|stock\?\.price)/,
    "v20 quote rendering must not fall back to a mutable stock adapter");
  const loadV19Start = smart.indexOf("async function loadV19()");
  const loadV19End = smart.indexOf("async function loadWatchRows()", loadV19Start);
  const loadV19Block = smart.slice(loadV19Start, loadV19End);
  assert.ok(loadV19Start >= 0 && loadV19End > loadV19Start);
  assert.ok(loadV19Block.indexOf("if (v20ShellActive) return;") < loadV19Block.indexOf("void optionalMarketJson()"),
    "the v20 shell must return before starting the mutable v19 benchmark adapter");
  assert.doesNotMatch(smart, /refresh=1|loadSnapshot\(true\)/,
    "public refresh controls must never invoke privileged refresh parameters");
  assert.match(ui, /不會儲存資金、成本或交易紀錄/);
  assert.match(ui, /未通過或待確認條件/);
  assert.match(ui, /機率尚未公開/);
  assert.match(ui, /MIN_VALIDATION_SAMPLES = 100/);
  assert.match(ui, /策略驗證中心/);
  assert.match(ui, /\/backtest\?model=/);
  assert.match(ui, /成本後實際結果/);
  assert.match(ui, /平均超額報酬/);
  assert.match(ui, /已實現批次回撤/);
  assert.match(ui, /平均 MFE/);
  assert.match(ui, /平均 MAE/);
  assert.match(ui, /不產生成功率或上漲機率/);
  assert.match(ui, /HORIZONS = \{ short: \[2, 3, 5, 10\], medium: \[10, 20, 40\] \}/);
  assert.match(ui, /RANKING_HORIZONS = \{ short: HORIZONS\.short, medium: \['blend', \.\.\.HORIZONS\.medium\] \}/);
  assert.match(ui, /DEFAULT_HORIZON = \{ short: 5, medium: 'blend' \}/,
    "the public medium ranking must default to the three-horizon blend");
  assert.doesNotMatch(ui, /medium: \[20, 40, 60\]/);
  assert.match(ui, /String\(value \|\| ''\)\.toLowerCase\(\) === 'blend' \? 'blend' : num\(value\)/,
    "public rows must preserve the blend horizon instead of coercing it to NaN");
  assert.match(ui, /model === 'medium' && horizon === 'blend'/,
    "medium blend rows, including home mediumTop, must remain publicly visible");
  assert.match(ui, /horizon: normalizeRankingHorizon\(model, page\.horizon\)/);
  assert.doesNotMatch(ui, /horizon: Number\(page\.horizon\)/,
    "the ranking query must send horizon=blend verbatim");
  assert.match(ui, /normalizeRankingHorizon\(model, event\.target\.value\)/,
    "the period filter must retain the blend string");
  assert.match(ui, /綜合（10／20／40 日）/);
  assert.match(ui, /中期綜合（非單一期）/);
  assert.match(ui, /10／20／40 日依 25%／50%／25% 組成/);
  assert.match(ui, /componentHorizons/);
  assert.match(ui, /blendWeights/);
  assert.match(ui, /function rawOpportunityValue[\s\S]*rawOpportunityScore/,
    "visible opportunity scores must come from the raw score field");
  assert.doesNotMatch(ui, /\.opportunityScore\b/,
    "the deprecated net-backed opportunityScore alias must never be presented as a raw opportunity score");
  assert.match(ui, /visibleItems\.map\(row => modelCard\(row\)\)/,
    "ranking cards must use only sanitized immutable rows and preserve the API rank");
  assert.match(ui, /supportedPayload = payload => \['20\.2', '20\.2\.1'\]\.includes\(String\(payload\?\.version \|\| ''\)\)/,
    "older browser caches must never enter the immutable v20.2 read model");
  assert.match(ui, /const CACHE_SCHEMA = 'v20\.2-immutable-2'/);
  assert.match(ui, /const CACHE_BUILD = new URL\(document\.currentScript\?\.src \|\| location\.href, location\.href\)\.searchParams\.get\('v'\) \|\| '20\.2\.1'/,
    "browser cache compatibility must follow the exact loaded frontend build");
  assert.match(ui, /CACHE_MAX_AGE_MS = 7 \* 24 \* 60 \* 60 \* 1000/,
    "browser placeholders must expire after seven days");
  assert.match(ui, /parsed\?\.schema === CACHE_SCHEMA && parsed\?\.build === CACHE_BUILD/,
    "browser caches must require exact schema and frontend build compatibility");
  assert.match(ui, /page\.abortController\?\.abort\(\)[\s\S]*page\.querySignature = request\.signature[\s\S]*requestId !== page\.requestId \|\| request\.signature !== page\.querySignature/,
    "ranking filters must abort and reject stale immutable query signatures");
  assert.match(ui, /validationAbortController\?\.abort\(\)[\s\S]*validationQuerySignature = signature[\s\S]*requestId !== v20\.validationRequestId \|\| signature !== v20\.validationQuerySignature/,
    "validation filters must abort and reject stale immutable query signatures");
  assert.match(ui, /function watchDetailForPublication[\s\S]*samePublication\(candidate, v20\.home\)/,
    "watchlist details must belong to the current immutable publication");
  assert.match(ui, /while \(generation === v20\.watchGeneration\)[\s\S]*\.slice\(0, 20\)[\s\S]*index \+= 4/,
    "all watchlist stocks must load in waves of twenty with concurrency four");
  assert.match(ui, /v20\.detailCache\.clear\(\);\s*v20\.watchAttempted\.clear\(\);\s*v20\.watchErrors\.clear\(\);/,
    "a publication change must invalidate every watchlist detail state");
  assert.match(ui, /researchOnly/);
  assert.match(ui, /publicVisible/);
  assert.match(ui, /row\.rank, row\.rankPosition, row\.rank_position/);
  assert.match(ui, /成本後機會值/);
  assert.doesNotMatch(ui, /value="probability_desc"/);
  assert.match(ui, /qa\('\[data-v20-detail\]', modalRoot\)/,
    "related-stock actions inside the detail modal must be rebound after repaint");
  assert.match(ui, /modelState\?\.reason/,
    "empty model blocks must display the exact API diagnostic instead of a generic placeholder");
  assert.match(ui, /相對中性值/,
    "the detail UI must explain the stored market factor contribution without changing its formula");
  assert.doesNotMatch(ui, /item\.opportunityScore, item\.aiScore\?\.value, item\.score/,
    "legacy related-stock scores must not be presented as immutable v20.1 opportunity scores");
  assert.doesNotMatch(backendSource, /readV19Home|readV19Stock|stock_sync_state|fastestRisers|normalizeLegacyRelatedStock/,
    "the v20 API must not depend on mutable v19 or worker-state fallback data");
  assert.match(backendSource, /importantNewsState:[\s\S]*not_recorded_in_publication/,
    "missing immutable news must be disclosed explicitly instead of backfilled from v19");
  assert.doesNotMatch(ui, /localStorage\.setItem\([^\n]*(?:capital|cost|position)/i);
  assert.doesNotMatch(ui, /portfolio_positions/i,
    "the public UI must not read or mutate hidden portfolio records");
  const assetVersion = sw.match(/const CACHE='twss-v([^']+)'/)?.[1];
  assert.ok(assetVersion);
  const escapedAssetVersion = assetVersion.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  assert.match(sw, new RegExp(`v20\\.js\\?v=${escapedAssetVersion}`));
  assert.match(generator, /read\("public\/v20\.js"\)/);
  assert.match(generator, /path==="\/v20\.js"/);
  assert.ok((sw.match(/if\(response\.ok\)/g) || []).length >= 3,
    "the service worker must never cache maintenance or other non-success responses");
  assert.match(sw, /Promise\.allSettled\(STATIC\.map/,
    "maintenance responses must not make the whole service-worker install fail");
  assert.doesNotMatch(sw, /cache\.addAll\(STATIC\)/,
    "one unavailable precache URL must not delay the client update");
  assert.match(sw, /url\.pathname===HOME_SNAPSHOT_PATH[\s\S]*setTimeout\(\(\)=>resolve\(cached\),2000\)[\s\S]*Promise\.race\(\[networkFirst,timeout\]\)/,
    "the home read model must prefer the network and use cache only after two seconds");
  assert.match(sw, /previousPublication&&!sameHomePublication\(previousPublication,nextPublication\)[\s\S]*notifyHomePublication\(nextPublication\)/,
    "clients must be notified only when the immutable home publication changes");
  assert.match(sw, /key\.startsWith\('twss-'\)&&key!==CACHE/,
    "service-worker activation must leave unrelated same-origin caches intact");
  assert.match(ui, /twss-home-publication-updated[\s\S]*!samePublication\(event\.data\.publication, v20\.home\)[\s\S]*loadHome\(\)/,
    "the active page must refresh after a background publication-change notification");
  assert.equal(JSON.parse(manifest).start_url.includes(`v=${assetVersion}`), true);

  console.log("v20 API/UI contract: passed");
} finally {
  globalThis.fetch = originalFetch;
  if (originalInternalKey === undefined) delete process.env.TWSS_V20_INTERNAL_KEY;
  else process.env.TWSS_V20_INTERNAL_KEY = originalInternalKey;
  if (originalMarketSecretKey === undefined) delete process.env.MARKET_SUPABASE_SECRET_KEY;
  else process.env.MARKET_SUPABASE_SECRET_KEY = originalMarketSecretKey;
  if (originalMarketServiceKey === undefined) delete process.env.MARKET_SUPABASE_SERVICE_ROLE_KEY;
  else process.env.MARKET_SUPABASE_SERVICE_ROLE_KEY = originalMarketServiceKey;
  if (originalSecretKey === undefined) delete process.env.SUPABASE_SECRET_KEY;
  else process.env.SUPABASE_SECRET_KEY = originalSecretKey;
  if (originalServiceKey === undefined) delete process.env.SUPABASE_SERVICE_ROLE_KEY;
  else process.env.SUPABASE_SERVICE_ROLE_KEY = originalServiceKey;
  if (originalPublishableKey === undefined) delete process.env.SUPABASE_PUBLISHABLE_KEY;
  else process.env.SUPABASE_PUBLISHABLE_KEY = originalPublishableKey;
  if (originalFinnhubKey === undefined) delete process.env.FINNHUB_API_KEY;
  else process.env.FINNHUB_API_KEY = originalFinnhubKey;
  if (originalAlphaVantageKey === undefined) delete process.env.ALPHA_VANTAGE_API_KEY;
  else process.env.ALPHA_VANTAGE_API_KEY = originalAlphaVantageKey;
}
