import assert from "node:assert/strict";
import { deepAsOf } from "../src/opportunity-engine.js";
import {
  MEDIUM_HORIZONS,
  MEDIUM_RESEARCH_HORIZONS,
  MEDIUM_WEIGHTS,
  SHORT_HORIZONS,
  SHORT_WEIGHTS,
  applyCalibration,
  calculatePositionSize,
  estimateExecutionCosts,
  scoreMediumTerm,
  scoreShortTerm,
} from "../src/v20-models.js";
import {
  V20_HORIZONS as PRODUCTION_HORIZONS,
  V20_MODEL_VERSION as PRODUCTION_MODEL_VERSION,
  scoreCacheRow,
} from "../supabase/functions/_shared/v20-model.js";
import {
  buildCalibrationBuckets,
  executionCosts,
  v20BacktestInternals,
  walkForwardBacktest,
} from "../src/v20-backtest.js";

const iso = (offset) => {
  const date = new Date(Date.UTC(2023, 0, 2 + offset));
  return date.toISOString().slice(0, 10);
};

function syntheticCandidate(sessionCount = 700) {
  const priceHistory = Array.from({ length: sessionCount }, (_, index) => {
    const base = 80 + index * 0.08 + Math.sin(index / 13) * 0.7;
    const close = Number(base.toFixed(2));
    return {
      date: iso(index),
      open: Number((close - 0.12).toFixed(2)),
      high: Number((close + 1).toFixed(2)),
      low: Number((close - 1).toFixed(2)),
      close,
      volume: 10_000 + index * 4,
      value: 500_000_000 + index * 100_000,
    };
  });
  const revenueHistory = Array.from({ length: 30 }, (_, index) => ({
    date: iso(index * 20),
    availableAt: iso(index * 20 + 10),
    period: `${2023 + Math.floor(index / 12)}-${String(index % 12 + 1).padStart(2, "0")}`,
    year: 2023 + Math.floor(index / 12),
    month: index % 12 + 1,
    revenue: 1_000 + index * 60,
    yoy: 8 + index * 0.7,
    mom: 2,
  }));
  const financialHistory = Array.from({ length: 12 }, (_, index) => ({
    date: iso(index * 55),
    availableAt: iso(index * 55 + 45),
    eps: 1 + index * 0.15,
    revenue: 3_000 + index * 200,
    grossMargin: 35 + index * 0.2,
    operatingMargin: 15 + index * 0.15,
    cashConversion: 1.1,
    operatingCashFlow: 900,
    inventory: 500 + index * 5,
    receivables: 400 + index * 4,
    debtRatio: 30,
  }));
  const institutionalHistory = priceHistory.map((row) => ({
    date: row.date,
    foreign: 800,
    trust: 250,
    dealer: 50,
    inst: 1_100,
    intensity: 2.5,
  }));
  const marginHistory = priceHistory.map((row, index) => ({
    date: row.date,
    marginBalance: 10_000 - index,
    marginLimit: 100_000,
  }));
  const contextHistory = priceHistory.map((row) => ({
    date: row.date,
    availableAt: row.date,
    regime: "bull",
    marketScore: 78,
    marketRiskScore: 22,
    globalSectorScore: 72,
    industryTrendScore: 82,
    industryDemandScore: 76,
    industryRiskScore: 18,
    relativeStrengthPercentile: 85,
    newsEventScore: 76,
    newsReliability: 95,
    eventDurationScore: 75,
    eventRiskScore: 15,
    valuationScore: 75,
    valuationRiskScore: 25,
    peValuePercentile: 72,
    pbValuePercentile: 68,
  }));
  const riskHistory = priceHistory.map((row) => ({
    date: row.date,
    availableAt: row.date,
    coverageComplete: true,
    hardExcluded: false,
    attention: false,
  }));
  return {
    stock: {
      symbol: "2330",
      name: "測試股票",
      market: "listed",
      instrumentType: "stock",
      industry: "半導體",
    },
    deep: {
      instrumentType: "stock",
      priceHistory,
      revenueHistory,
      financial: { history: financialHistory },
      institutional: { history: institutionalHistory },
      margin: { history: marginHistory },
      missing: [],
    },
    contextHistory,
    riskHistory,
  };
}

assert.deepEqual(SHORT_HORIZONS, [2, 3, 5, 10]);
assert.deepEqual(MEDIUM_HORIZONS, [10, 20, 40]);
assert.deepEqual(MEDIUM_RESEARCH_HORIZONS, [60]);
assert.deepEqual(PRODUCTION_HORIZONS.medium, [10, 20, 40]);
assert.equal(PRODUCTION_MODEL_VERSION, "20.2");
assert.equal(Object.values(SHORT_WEIGHTS).reduce((total, value) => total + value, 0), 100);
assert.equal(Object.values(MEDIUM_WEIGHTS).reduce((total, value) => total + value, 0), 100);
assert.notDeepEqual(SHORT_WEIGHTS, MEDIUM_WEIGHTS, "short and medium weights must remain independent");
assert.deepEqual(SHORT_WEIGHTS, {
  priceVolumeTrend: 25,
  institutional: 20,
  relativeIndustry: 15,
  volatilityRiskReward: 15,
  marketGlobal: 10,
  revenueEventCatalyst: 10,
  liquidityExecutionCost: 5,
});
assert.deepEqual(MEDIUM_WEIGHTS, {
  revenueProfitGrowth: 25,
  financialQuality: 15,
  mediumTrend: 20,
  institutionalPositioning: 15,
  industryEnvironment: 10,
  valuationReasonableness: 10,
  liquidityRisk: 5,
});

const candidate = syntheticCandidate();
const asOf = candidate.deep.priceHistory[560].date;
const deep = deepAsOf(candidate.deep, asOf);
const stock = {
  ...candidate.stock,
  close: deep.priceHistory.at(-1).close,
  volume: deep.priceHistory.at(-1).volume,
  value: deep.priceHistory.at(-1).value,
};
const context = candidate.contextHistory[560];
const risk = candidate.riskHistory[560];

const shortWithoutHistory = scoreShortTerm({ stock, deep, context, risk, asOf });
const mediumWithoutHistory = scoreMediumTerm({ stock, deep, context, risk, asOf });
assert.equal(shortWithoutHistory.model, "short");
assert.equal(mediumWithoutHistory.model, "medium");
assert.notDeepEqual(shortWithoutHistory.components.map((row) => row.key), mediumWithoutHistory.components.map((row) => row.key));
assert.equal(shortWithoutHistory.forecasts["5"].upProbability, null, "probabilities must not be invented");
assert.equal(shortWithoutHistory.forecasts["5"].expectedNetReturn, null, "uncalibrated expected return must stay null");
assert.equal(shortWithoutHistory.gates.find((row) => row.key === "positive_expectancy").status, "unknown");
assert.ok(shortWithoutHistory.rawOpportunityScore >= shortWithoutHistory.netOpportunityScore);
assert.equal(shortWithoutHistory.opportunityScore, shortWithoutHistory.netOpportunityScore);
assert.ok(shortWithoutHistory.costs.totalPct > 0);
const noNewsSignal = scoreShortTerm({
  stock,
  deep,
  context: { ...context, newsEventScore: null, newsReliability: null },
  risk,
  asOf,
});
assert.equal(noNewsSignal.missing.includes("可信新聞與公告影響"), false, "no recent event is neutral, not a missing data source");

const productionRow = {
  symbol: "2330",
  data_date: "2026-07-16",
  confidence: 95,
  group_name: "listed",
  stock: {
    symbol: "2330",
    name: "台積電",
    market: "listed",
    instrumentType: "stock",
    industry: "半導體業",
    close: 100,
    value: 600_000_000,
    volume: 15_000,
  },
  analysis: {
    price: {
      rows: 300,
      sufficient: true,
      lastClose: 100,
      atr14: 2.5,
      atrPct: 2.5,
      volumeRatio: 1.4,
      ma20: 96,
      ma60: 90,
      ma120: 82,
      ma20Slope5: 1.2,
      ma60Slope5: 0.8,
      relative20: 5,
      relative60: 9,
      distanceMa20: 4,
      rsi14: 62,
      breakout20: true,
      high20: 102,
    },
    institutional: { days: 60, inst5: 5_000, inst20: 12_000, intensity5: 2.5 },
    revenue: { months: 24, yoy: 18, avg3Yoy: 16, acceleration3: 3 },
    financial: { quarters: 12, debtRatio: 30, operatingMargin: 22, ttmOperatingCashFlow: 1_000 },
  },
  result: {
    categories: [
      { key: "technical", score: 85, items: [{ key: "volume", score: 82 }, { key: "breakout", score: 88 }, { key: "relative20", score: 84 }] },
      { key: "trend", score: 82, items: [] },
      { key: "chip", score: 80, items: [] },
      { key: "market", score: 78, items: [{ key: "industry_breadth", score: 80 }, { key: "industry_change", score: 76 }] },
      { key: "growth", score: 84, items: [] },
      { key: "valuation", score: 72, items: [] },
    ],
    reasons: ["價量同步轉強"],
    risk: { hardExcluded: false, deduction: 5, flags: [], hardReasons: [] },
  },
};
const productionScored = scoreCacheRow(productionRow, {
  marketContext: { regime: "bull", regime_score: 35, data_date: "2026-07-16" },
  newsRows: [],
  calibrationBuckets: [],
});
assert.equal(productionScored.signals.length, 8, "staging requires four short and four medium horizons per symbol");
assert.equal(productionScored.publicSignals.length, 7, "only seven horizons are public");
assert.deepEqual(
  productionScored.publicSignals.filter((row) => row.model_key === "medium").map((row) => row.horizon_days),
  [10, 20, 40],
  "public medium signals must exclude the 60-day research horizon",
);
assert.deepEqual(
  productionScored.researchSignals.map((row) => [row.model_key, row.horizon_days, row.research_only]),
  [["medium", 60, true]],
  "60-day results must remain available only in the research channel",
);
assert.deepEqual(
  productionScored.signals.filter((row) => row.model_key === "medium").map((row) => [row.horizon_days, row.research_only]),
  [[10, false], [20, false], [40, false], [60, true]],
  "staging must preserve the 60-day research signal for point-in-time validation",
);
for (const signal of productionScored.signals) {
  assert.equal(signal.prediction_basis, "uncalibrated");
  assert.equal(signal.up_probability, null, "production must not synthesize an uncalibrated probability");
  assert.equal(signal.expected_return_net, null, "production must not synthesize an uncalibrated expected return");
  assert.equal(signal.expected_excess_return_gross, null);
  assert.equal(signal.expected_excess_return_net, null);
  assert.equal(signal.expected_value, null, "legacy expected-value field must also stay null");
  assert.equal(signal.return_p10, null);
  assert.equal(signal.return_p50, null);
  assert.equal(signal.return_p90, null);
  assert.equal(signal.opportunity_score, signal.net_opportunity_score);
  assert.ok(signal.raw_opportunity_score >= signal.net_opportunity_score);
  assert.ok(signal.estimated_total_cost_pct > 0);
  assert.ok(signal.cost_penalty_score > 0);
  assert.ok(signal.turnover_exposure > 0);
  for (const key of [
    "raw_opportunity_score",
    "net_opportunity_score",
    "estimated_commission_pct",
    "estimated_tax_pct",
    "estimated_slippage_pct",
    "estimated_spread_pct",
    "estimated_total_cost_pct",
    "downside_penalty_score",
    "turnover_penalty_score",
    "cost_penalty_score",
    "turnover_exposure",
    "liquidity_grade",
    "recommended_holding_days",
  ]) {
    assert.notEqual(signal[key], null, `v20.1 staging field ${key} must be non-null`);
    assert.notEqual(signal[key], undefined, `v20.1 staging field ${key} must be present`);
  }
  const reconciledCost = signal.estimated_commission_pct + signal.estimated_tax_pct
    + signal.estimated_slippage_pct + signal.estimated_spread_pct;
  assert.ok(Math.abs(signal.estimated_total_cost_pct - reconciledCost) <= 0.0001, "cost sum must satisfy publisher tolerance");
  assert.equal(typeof signal.feature_scores, "object");
  assert.equal(typeof signal.gate_results, "object");
  assert.ok(Array.isArray(signal.reasons));
  assert.ok(Array.isArray(signal.risks));
  assert.ok(Array.isArray(signal.invalidation_conditions));
  assert.equal(typeof signal.source_dates, "object");
}

const productionShort5 = productionScored.signals.find((row) => row.model_key === "short" && row.horizon_days === 5);
const productionCalibrationBucket = {
  model_key: "short",
  strategy_key: "momentum_breakout",
  horizon_days: 5,
  market_regime: "bull",
  score_decile: Math.floor(productionShort5.net_opportunity_score / 10),
  sample_count: 120,
  calibrated_probability: 63,
  average_net_return: 1.35,
  return_p10: -2.5,
  return_p50: 1.1,
  return_p90: 5.4,
  average_mfe: 3.8,
  average_mae: -1.9,
  target_first_probability: 57,
};
const productionCalibrated = scoreCacheRow(productionRow, {
  marketContext: { regime: "bull", regime_score: 35, data_date: "2026-07-16" },
  newsRows: [],
  calibrationBuckets: [{ ...productionCalibrationBucket, average_excess_return_net: 0.92 }],
}).signals.find((row) => row.model_key === "short" && row.horizon_days === 5);
assert.equal(productionCalibrated.prediction_basis, "walk-forward-calibration");
assert.equal(productionCalibrated.calibration_sample_count, 120);
assert.equal(productionCalibrated.expected_excess_return_net, 0.92);
assert.equal(productionCalibrated.expected_excess_return_gross, null, "gross excess return remains null until calibration stores it explicitly");

const productionWithoutBenchmark = scoreCacheRow(productionRow, {
  marketContext: { regime: "bull", regime_score: 35, data_date: "2026-07-16" },
  newsRows: [],
  calibrationBuckets: [productionCalibrationBucket],
}).signals.find((row) => row.model_key === "short" && row.horizon_days === 5);
assert.equal(productionWithoutBenchmark.expected_excess_return_net, null,
  "a net return must never be relabeled as benchmark-adjusted excess return");

const empty = scoreShortTerm({ stock: { symbol: "9999" }, deep: {}, context: {}, risk: {} });
assert.equal(empty.score, null);
assert.equal(empty.riskScore, null);
assert.equal(empty.action, "資料不足");

const manualBuckets = SHORT_HORIZONS.map((horizon) => ({
  model: "short",
  style: shortWithoutHistory.style,
  horizonDays: horizon,
  regime: "bull",
  scoreDecile: Math.floor(shortWithoutHistory.score / 10),
  sampleSize: 120,
  upProbability: 64,
  expectedNetReturn: 1.25,
  returnP10: -3.1,
  returnP50: 1.1,
  returnP90: 6.2,
  averageMfe: 4.1,
  averageMae: -2.2,
  targetFirstProbability: 58,
}));
const calibrated = scoreShortTerm({ stock, deep, context, risk, asOf, calibrationBuckets: manualBuckets });
assert.equal(calibrated.forecasts["5"].dataState, "calibrated");
assert.equal(calibrated.forecasts["5"].upProbability, 64);
assert.equal(calibrated.gates.find((row) => row.key === "positive_expectancy").status, "pass");

const applied = applyCalibration(shortWithoutHistory, manualBuckets);
assert.equal(applied["2"].sampleSize, 120);

const underMinimumBuckets = manualBuckets.map((row) => ({ ...row, sampleSize: 99 }));
assert.equal(applyCalibration(shortWithoutHistory, underMinimumBuckets)["2"].dataState, "insufficient_history");

assert.deepEqual(calculatePositionSize({ capital: 1_000_000, riskRatio: 0.005, entryPrice: 100, stopLoss: 95 }), {
  status: "ready",
  maximumRiskAmount: 5000,
  shares: 1000,
  lots: 1,
});
assert.equal(calculatePositionSize({ capital: 1_000_000, riskRatio: 0.02, entryPrice: 100, stopLoss: 95 }).status, "invalid_input");

const stockCosts = executionCosts({ group: "listed", entryPrice: 100, exitPrice: 105 });
const etfCosts = executionCosts({ group: "etf", entryPrice: 100, exitPrice: 105 });
assert.equal(stockCosts.roundTripCostPct, 0.885);
assert.equal(etfCosts.roundTripCostPct, 0.685);

const liquidStockEstimate = estimateExecutionCosts({
  group: "listed",
  averageDailyValue: 1_000_000_000,
  atrPct: 2,
  price: 500,
});
const illiquidOtcEstimate = estimateExecutionCosts({
  group: "otc",
  averageDailyValue: 5_000_000,
  atrPct: 9,
  price: 15,
});
const liquidEtfEstimate = estimateExecutionCosts({
  group: "etf",
  averageDailyValue: 1_000_000_000,
  atrPct: 2,
  price: 100,
});
const smallOrderEstimate = estimateExecutionCosts({
  group: "listed",
  averageDailyValue: 1_000_000_000,
  atrPct: 2,
  price: 500,
  expectedOrderValue: 5_000,
});
assert.ok(illiquidOtcEstimate.slippagePct > liquidStockEstimate.slippagePct);
assert.ok(illiquidOtcEstimate.spreadPct > liquidStockEstimate.spreadPct);
assert.ok(illiquidOtcEstimate.totalPct > liquidStockEstimate.totalPct);
assert.ok(liquidEtfEstimate.taxPct < liquidStockEstimate.taxPct);
assert.ok(smallOrderEstimate.commissionPct > liquidStockEstimate.commissionPct, "minimum commission must affect small orders");
assert.equal(
  liquidStockEstimate.totalPct,
  Number((liquidStockEstimate.commissionPct + liquidStockEstimate.taxPct + liquidStockEstimate.slippagePct + liquidStockEstimate.spreadPct).toFixed(4)),
  "stored cost components must reconcile exactly with the total",
);

const calibrationRows = [];
for (let decile = 6; decile <= 8; decile += 1) {
  for (let index = 0; index < 80; index += 1) {
    // Deliberately non-monotonic raw win rates; isotonic calibration must repair it.
    const winning = index < ({ 6: 48, 7: 32, 8: 64 }[decile]);
    calibrationRows.push({
      model: "short",
      style: "trend_pullback",
      horizonDays: 5,
      regime: "bull",
      score: decile * 10 + 2,
      grossReturn: winning ? 3 : -2,
      netReturn: winning ? 2.115 : -2.885,
      costPct: 0.885,
      mfe: winning ? 4 : 1,
      mae: winning ? -1 : -3,
      targetFirst: winning,
    });
  }
}
const buckets = buildCalibrationBuckets(calibrationRows).filter((row) => row.style === "trend_pullback").sort((a, b) => a.scoreDecile - b.scoreDecile);
assert.equal(buckets.length, 3);
assert.ok(buckets[0].upProbability <= buckets[1].upProbability && buckets[1].upProbability <= buckets[2].upProbability, "calibrated probability must be monotonic");
assert.equal(buckets[0].calibrationMethod, "beta_2_2_isotonic");

const futureContext = {
  contextHistory: [
    { availableAt: "2025-01-01", marketScore: 20 },
    { availableAt: "2025-02-01", marketScore: 99 },
  ],
};
assert.equal(v20BacktestInternals.contextAsOf(futureContext, "2025-01-15").marketScore, 20, "future context must not leak backward");

const sameBarSignal = {
  tradePlan: { stopLoss: 95, firstTarget: 105 },
};
const sameBarHistory = [
  { date: "2025-01-01", close: 100, open: 100, high: 101, low: 99 },
  { date: "2025-01-02", close: 101, open: 100, high: 106, low: 94 },
  { date: "2025-01-03", close: 102, open: 101, high: 103, low: 100 },
];
const sameBar = v20BacktestInternals.evaluatePath({ signal: sameBarSignal, priceHistory: sameBarHistory, signalIndex: 0, horizon: 2, group: "listed", costOverrides: {} });
assert.equal(sameBar.targetFirst, false);
assert.equal(sameBar.tradeExitReason, "stop_first_same_bar");

const insufficient = walkForwardBacktest({ candidates: [syntheticCandidate(300)] });
assert.equal(insufficient.status, "insufficient_history");
assert.equal(insufficient.noLookAhead, true);

const backtest = walkForwardBacktest({ candidates: [candidate], models: ["short", "medium"], testStepSessions: 20, topN: 1 });
assert.equal(backtest.noLookAhead, true);
assert.equal(backtest.methodology.entry, "next_trading_day_open");
assert.equal(backtest.methodology.sameBarConflict, "stop_first");
assert.ok(backtest.outcomes.length > 0, "walk-forward should produce point-in-time outcomes for eligible synthetic candidates");
assert.ok(backtest.outcomes.every((row) => row.entryDate > row.signalDate));
assert.ok(backtest.outcomes.every((row) => row.netReturn < row.grossReturn));

console.log("v20 model/backtest tests passed: independent models, hard gates, null forecasts, costs, point-in-time walk-forward, MFE/MAE, and monotonic calibration");
