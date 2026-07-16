import assert from "node:assert/strict";
import { deepAsOf } from "../src/opportunity-engine.js";
import {
  MEDIUM_HORIZONS,
  MEDIUM_WEIGHTS,
  SHORT_HORIZONS,
  SHORT_WEIGHTS,
  applyCalibration,
  calculatePositionSize,
  scoreMediumTerm,
  scoreShortTerm,
} from "../src/v20-models.js";
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
assert.deepEqual(MEDIUM_HORIZONS, [20, 40, 60]);
assert.equal(Object.values(SHORT_WEIGHTS).reduce((total, value) => total + value, 0), 100);
assert.equal(Object.values(MEDIUM_WEIGHTS).reduce((total, value) => total + value, 0), 100);
assert.notDeepEqual(SHORT_WEIGHTS, MEDIUM_WEIGHTS, "short and medium weights must remain independent");

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
assert.equal(shortWithoutHistory.official, false, "no calibrated expectation means no formal recommendation");
assert.equal(shortWithoutHistory.forecasts["5"].upProbability, null, "probabilities must not be invented");
assert.equal(shortWithoutHistory.gates.find((row) => row.key === "positive_expectancy").status, "unknown");

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
  sampleSize: 80,
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
assert.equal(applied["2"].sampleSize, 80);

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
