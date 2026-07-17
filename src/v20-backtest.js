import { deepAsOf } from "./opportunity-engine.js";
import {
  MEDIUM_HORIZONS,
  SHORT_HORIZONS,
  V20_MODEL_VERSION,
  scoreMediumTerm,
  scoreShortTerm,
} from "./v20-models.js";

const finite = (value) => value !== null && value !== undefined && Number.isFinite(Number(value));
const round = (value, digits = 2) => finite(value) ? Number(Number(value).toFixed(digits)) : null;
const sum = (values) => values.filter(finite).reduce((total, value) => total + Number(value), 0);
const mean = (values) => {
  const usable = values.filter(finite).map(Number);
  return usable.length ? sum(usable) / usable.length : null;
};

export const V20_BACKTEST_DEFAULTS = Object.freeze({
  minimumTrainingSessions: 504,
  testStepSessions: 20,
  topN: 10,
  buyCommissionRate: 0.001425,
  sellCommissionRate: 0.001425,
  stockSellTaxRate: 0.003,
  etfSellTaxRate: 0.001,
  slippageRatePerSide: 0.001,
  spreadRatePerSide: 0.0005,
});

function quantile(values, probability) {
  const sorted = values.filter(finite).map(Number).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const position = (sorted.length - 1) * probability;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
}

function groupOf(stock) {
  if (String(stock?.instrumentType || "").toUpperCase() === "ETF") return "etf";
  const market = String(stock?.market || "").toLowerCase();
  return ["otc", "tpex", "上櫃"].some((key) => market.includes(key)) ? "otc" : "listed";
}

export function executionCosts({ group = "listed", entryPrice, exitPrice, ...overrides } = {}) {
  const rates = { ...V20_BACKTEST_DEFAULTS, ...overrides };
  const sellTaxRate = group === "etf" ? rates.etfSellTaxRate : rates.stockSellTaxRate;
  const buyFrictionRate = rates.buyCommissionRate + rates.slippageRatePerSide + rates.spreadRatePerSide;
  const sellFrictionRate = rates.sellCommissionRate + sellTaxRate + rates.slippageRatePerSide + rates.spreadRatePerSide;
  return {
    buyCommissionRate: rates.buyCommissionRate,
    sellCommissionRate: rates.sellCommissionRate,
    sellTaxRate,
    slippageRatePerSide: rates.slippageRatePerSide,
    spreadRatePerSide: rates.spreadRatePerSide,
    buyFrictionRate,
    sellFrictionRate,
    roundTripCostPct: round((buyFrictionRate + sellFrictionRate) * 100, 4),
    effectiveEntryPrice: finite(entryPrice) ? round(Number(entryPrice) * (1 + buyFrictionRate), 6) : null,
    effectiveExitPrice: finite(exitPrice) ? round(Number(exitPrice) * (1 - sellFrictionRate), 6) : null,
  };
}

function returnsWithCosts(entryPrice, exitPrice, group, overrides = {}) {
  if (!finite(entryPrice) || !finite(exitPrice) || Number(entryPrice) <= 0) {
    return { grossReturn: null, netReturn: null, costPct: null };
  }
  const costs = executionCosts({ group, entryPrice, exitPrice, ...overrides });
  const grossReturn = (Number(exitPrice) / Number(entryPrice) - 1) * 100;
  const netReturn = (costs.effectiveExitPrice / costs.effectiveEntryPrice - 1) * 100;
  return { grossReturn: round(grossReturn, 4), netReturn: round(netReturn, 4), costPct: costs.roundTripCostPct };
}

function bucketSummary(rows) {
  if (!rows.length) return null;
  const gross = rows.map((row) => row.grossReturn).filter(finite);
  const net = rows.map((row) => row.netReturn).filter(finite);
  const wins = gross.filter((value) => value > 0);
  const losses = gross.filter((value) => value <= 0);
  const sampleSize = net.length;
  if (!sampleSize) return null;
  const smoothedWinProbability = (wins.length + 2) / (sampleSize + 4);
  const averageGrossWin = mean(wins) ?? 0;
  const averageGrossLoss = Math.abs(mean(losses) ?? 0);
  const averageCost = mean(rows.map((row) => row.costPct)) ?? 0;
  const expectedNetReturn = smoothedWinProbability * averageGrossWin - (1 - smoothedWinProbability) * averageGrossLoss - averageCost;
  const touches = rows.map((row) => row.targetFirst).filter((value) => typeof value === "boolean");
  return {
    sampleSize,
    upProbability: round(smoothedWinProbability * 100, 1),
    expectedNetReturn: round(expectedNetReturn),
    returnP10: round(quantile(net, 0.10)),
    returnP50: round(quantile(net, 0.50)),
    returnP90: round(quantile(net, 0.90)),
    averageMfe: round(mean(rows.map((row) => row.mfe))),
    averageMae: round(mean(rows.map((row) => row.mae))),
    targetFirstProbability: touches.length ? round((touches.filter(Boolean).length + 1) / (touches.length + 2) * 100, 1) : null,
    averageGrossWin: round(averageGrossWin),
    averageGrossLoss: round(averageGrossLoss),
    averageCostPct: round(averageCost, 4),
  };
}

function poolAdjacentViolators(rows) {
  const blocks = rows.map((row) => ({
    start: row.scoreDecile,
    end: row.scoreDecile,
    weight: row.sampleSize,
    value: row.upProbability,
  }));
  for (let index = 0; index < blocks.length - 1;) {
    if (blocks[index].value <= blocks[index + 1].value) {
      index += 1;
      continue;
    }
    const left = blocks[index];
    const right = blocks[index + 1];
    const weight = left.weight + right.weight;
    blocks.splice(index, 2, {
      start: left.start,
      end: right.end,
      weight,
      value: (left.value * left.weight + right.value * right.weight) / weight,
    });
    if (index > 0) index -= 1;
  }
  return rows.map((row) => {
    const block = blocks.find((entry) => row.scoreDecile >= entry.start && row.scoreDecile <= entry.end);
    return { ...row, upProbability: round(block?.value ?? row.upProbability, 1), calibrationMethod: "beta_2_2_isotonic" };
  });
}

function grouped(rows, keyBuilder) {
  const groups = new Map();
  rows.forEach((row) => {
    const key = keyBuilder(row);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  });
  return groups;
}

export function buildCalibrationBuckets(outcomes = []) {
  const usable = outcomes.filter((row) => finite(row.netReturn) && finite(row.grossReturn) && finite(row.score) && row.model && finite(row.horizonDays));
  const exactGroups = grouped(usable, (row) => [row.model, row.style || "unknown", row.horizonDays, row.regime || "unknown", Math.max(0, Math.min(9, Math.floor(Number(row.score) / 10)))].join("|"));
  let exact = [...exactGroups.entries()].map(([key, rows]) => {
    const [model, style, horizonDays, regime, scoreDecile] = key.split("|");
    return { model, style, horizonDays: Number(horizonDays), regime, scoreDecile: Number(scoreDecile), ...bucketSummary(rows) };
  }).filter((row) => row.sampleSize);

  const isotonicGroups = grouped(exact, (row) => [row.model, row.style, row.horizonDays, row.regime].join("|"));
  exact = [...isotonicGroups.values()].flatMap((rows) => poolAdjacentViolators(rows.sort((a, b) => a.scoreDecile - b.scoreDecile)));

  const fallbackGroups = grouped(usable, (row) => [row.model, row.horizonDays, row.regime || "unknown"].join("|"));
  const fallback = [...fallbackGroups.entries()].map(([key, rows]) => {
    const [model, horizonDays, regime] = key.split("|");
    return {
      model,
      style: "all",
      horizonDays: Number(horizonDays),
      regime,
      scoreDecile: null,
      calibrationMethod: "beta_2_2",
      ...bucketSummary(rows),
    };
  }).filter((row) => row.sampleSize);
  return [...exact, ...fallback];
}

function latestAsOf(rows, asOf) {
  return (Array.isArray(rows) ? rows : [])
    .filter((row) => {
      const availableAt = String(row?.availableAt || row?.date || "");
      return availableAt && availableAt <= asOf;
    })
    .sort((a, b) => String(a.availableAt || a.date).localeCompare(String(b.availableAt || b.date)))
    .at(-1) || null;
}

function stockAsOf(candidate, asOf, slicedDeep) {
  const history = latestAsOf(candidate.stockHistory, asOf);
  const priceRow = slicedDeep?.priceHistory?.at(-1) || {};
  const staticStock = candidate.stock || {};
  return {
    symbol: staticStock.symbol,
    name: staticStock.name,
    market: staticStock.market,
    instrumentType: staticStock.instrumentType,
    industry: staticStock.industry,
    close: priceRow.close ?? history?.close ?? null,
    volume: priceRow.volume ?? history?.volume ?? null,
    value: priceRow.value ?? history?.value ?? null,
    pe: history?.pe ?? null,
    pb: history?.pb ?? null,
    yield: history?.yield ?? null,
  };
}

function contextAsOf(candidate, asOf) {
  if (typeof candidate.contextAsOf === "function") return candidate.contextAsOf(asOf) || {};
  const row = latestAsOf(candidate.contextHistory, asOf);
  return row ? { ...row } : candidate.context?.pointInTime === true ? { ...candidate.context } : {};
}

function riskAsOf(candidate, asOf) {
  const row = latestAsOf(candidate.riskHistory, asOf);
  return row ? { ...row } : candidate.risk?.pointInTime === true ? { ...candidate.risk } : { coverageComplete: false };
}

function lockedLimitUp(row, priorClose) {
  if (!finite(priorClose) || !finite(row?.low) || !finite(row?.high)) return false;
  return Number(row.low) >= Number(priorClose) * 1.094 && Math.abs(Number(row.high) - Number(row.low)) < 1e-8;
}

function lockedLimitDown(row, priorClose) {
  if (!finite(priorClose) || !finite(row?.low) || !finite(row?.high)) return false;
  return Number(row.high) <= Number(priorClose) * 0.906 && Math.abs(Number(row.high) - Number(row.low)) < 1e-8;
}

function evaluatePath({ signal, priceHistory, signalIndex, horizon, group, costOverrides }) {
  const signalRow = priceHistory[signalIndex];
  const entryRow = priceHistory[signalIndex + 1];
  const scheduledExit = priceHistory[signalIndex + horizon];
  if (!entryRow || !scheduledExit || !finite(entryRow.open) || lockedLimitUp(entryRow, signalRow?.close)) return null;
  const entryPrice = Number(entryRow.open);
  const path = priceHistory.slice(signalIndex + 1, signalIndex + horizon + 1);
  const stop = signal.tradePlan?.stopLoss;
  const target = signal.tradePlan?.firstTarget;
  let targetFirst = null;
  let tradeExitPrice = Number(scheduledExit.close);
  let tradeExitDate = scheduledExit.date;
  let exitReason = "horizon_close";
  let deferredStop = false;

  for (let index = 0; index < path.length; index += 1) {
    const row = path[index];
    const prior = priceHistory[signalIndex + index]?.close;
    if (deferredStop) {
      if (lockedLimitDown(row, prior)) continue;
      tradeExitPrice = finite(row.open) ? Number(row.open) : Number(row.close);
      tradeExitDate = row.date;
      exitReason = "deferred_stop_after_limit_down";
      targetFirst = false;
      deferredStop = false;
      break;
    }
    const hitStop = finite(stop) && finite(row.low) && Number(row.low) <= Number(stop);
    const hitTarget = finite(target) && finite(row.high) && Number(row.high) >= Number(target);
    if (hitStop) {
      if (lockedLimitDown(row, prior)) {
        deferredStop = true;
        continue;
      }
      tradeExitPrice = finite(row.open) && Number(row.open) < Number(stop) ? Number(row.open) : Number(stop);
      tradeExitDate = row.date;
      exitReason = hitTarget ? "stop_first_same_bar" : "stop";
      targetFirst = false;
      break;
    }
    if (hitTarget) {
      tradeExitPrice = Number(target);
      tradeExitDate = row.date;
      exitReason = "target";
      targetFirst = true;
      break;
    }
  }

  if (deferredStop) {
    const future = priceHistory.slice(signalIndex + horizon + 1).find((row, index) => !lockedLimitDown(row, priceHistory[signalIndex + horizon + index]?.close));
    if (!future) return null;
    tradeExitPrice = finite(future.open) ? Number(future.open) : Number(future.close);
    tradeExitDate = future.date;
    exitReason = "deferred_stop_after_horizon";
    targetFirst = false;
  }

  const horizonReturn = returnsWithCosts(entryPrice, scheduledExit.close, group, costOverrides);
  const tradeReturn = returnsWithCosts(entryPrice, tradeExitPrice, group, costOverrides);
  const highs = path.map((row) => row.high).filter(finite).map(Number);
  const lows = path.map((row) => row.low).filter(finite).map(Number);
  return {
    entryDate: entryRow.date,
    entryPrice: round(entryPrice, 6),
    exitDate: scheduledExit.date,
    exitPrice: round(scheduledExit.close, 6),
    grossReturn: horizonReturn.grossReturn,
    netReturn: horizonReturn.netReturn,
    costPct: horizonReturn.costPct,
    mfe: highs.length ? round((Math.max(...highs) / entryPrice - 1) * 100) : null,
    mae: lows.length ? round((Math.min(...lows) / entryPrice - 1) * 100) : null,
    targetFirst,
    tradeExitDate,
    tradeExitPrice: round(tradeExitPrice, 6),
    tradeGrossReturn: tradeReturn.grossReturn,
    tradeNetReturn: tradeReturn.netReturn,
    tradeExitReason: exitReason,
  };
}

function calendarFromCandidates(candidates) {
  return [...new Set(candidates.flatMap((candidate) => (candidate.deep?.priceHistory || []).map((row) => row.date)))]
    .filter(Boolean)
    .sort();
}

function researchEligible(signal) {
  if (!finite(signal?.score) || !finite(signal?.riskScore) || !signal.style) return false;
  const structuralGates = signal.gates.filter((row) => row.key !== "positive_expectancy");
  return structuralGates.every((row) => row.status === "pass") && signal.riskScore < 75;
}

function modelSummary(outcomes, model, horizons) {
  const byHorizon = Object.fromEntries(horizons.map((horizon) => {
    const rows = outcomes.filter((row) => row.model === model && row.horizonDays === horizon && finite(row.netReturn));
    return [String(horizon), {
      sampleSize: rows.length,
      status: rows.length >= 100 ? "ready" : "insufficient_history",
      averageNetReturn: round(mean(rows.map((row) => row.netReturn))),
      winRate: rows.length ? round(rows.filter((row) => row.netReturn > 0).length / rows.length * 100, 1) : null,
      averageMfe: round(mean(rows.map((row) => row.mfe))),
      averageMae: round(mean(rows.map((row) => row.mae))),
    }];
  }));
  return { horizons: byHorizon, sampleSize: sum(Object.values(byHorizon).map((row) => row.sampleSize)) };
}

export function walkForwardBacktest({
  candidates = [],
  models = ["short", "medium"],
  minimumTrainingSessions = V20_BACKTEST_DEFAULTS.minimumTrainingSessions,
  testStepSessions = V20_BACKTEST_DEFAULTS.testStepSessions,
  topN = V20_BACKTEST_DEFAULTS.topN,
  costOverrides = {},
} = {}) {
  const calendar = calendarFromCandidates(candidates);
  const maximumHorizon = Math.max(...models.flatMap((model) => model === "short" ? SHORT_HORIZONS : MEDIUM_HORIZONS));
  if (calendar.length < minimumTrainingSessions + maximumHorizon + 1) {
    return {
      version: V20_MODEL_VERSION,
      generatedAt: new Date().toISOString(),
      status: "insufficient_history",
      noLookAhead: true,
      minimumTrainingSessions,
      availableSessions: calendar.length,
      outcomes: [],
      calibrationBuckets: [],
      models: {
        short: modelSummary([], "short", SHORT_HORIZONS),
        medium: modelSummary([], "medium", MEDIUM_HORIZONS),
      },
    };
  }

  const outcomes = [];
  for (let calendarIndex = minimumTrainingSessions - 1; calendarIndex < calendar.length - maximumHorizon; calendarIndex += testStepSessions) {
    const asOf = calendar[calendarIndex];
    const maturedOutcomes = outcomes.filter((row) => row.exitDate <= asOf);
    const calibrationBuckets = buildCalibrationBuckets(maturedOutcomes);
    for (const model of models) {
      const scorer = model === "short" ? scoreShortTerm : scoreMediumTerm;
      const horizons = model === "short" ? SHORT_HORIZONS : MEDIUM_HORIZONS;
      const ranked = candidates.map((candidate) => {
        const slicedDeep = deepAsOf(candidate.deep || {}, asOf);
        const stock = stockAsOf(candidate, asOf, slicedDeep);
        const context = contextAsOf(candidate, asOf);
        const risk = riskAsOf(candidate, asOf);
        const signal = scorer({ stock, deep: slicedDeep, context, risk, calibrationBuckets, asOf });
        return { candidate, stock, signal };
      }).filter((row) => researchEligible(row.signal))
        .sort((a, b) => b.signal.score - a.signal.score || a.signal.riskScore - b.signal.riskScore)
        .slice(0, topN);

      ranked.forEach(({ candidate, stock, signal }, rankIndex) => {
        const priceHistory = candidate.deep?.priceHistory || [];
        const signalIndex = priceHistory.findIndex((row) => row.date === asOf);
        if (signalIndex < 0) return;
        horizons.forEach((horizon) => {
          const evaluated = evaluatePath({ signal, priceHistory, signalIndex, horizon, group: groupOf(stock), costOverrides });
          if (!evaluated) return;
          outcomes.push({
            version: V20_MODEL_VERSION,
            model,
            style: signal.style,
            signalDate: asOf,
            symbol: signal.symbol,
            group: signal.group,
            industry: stock.industry || null,
            rank: rankIndex + 1,
            score: signal.score,
            riskScore: signal.riskScore,
            regime: signal.regime || "unknown",
            dataCompleteness: signal.dataCompleteness,
            horizonDays: horizon,
            forecastAtSignal: signal.forecasts[String(horizon)],
            ...evaluated,
          });
        });
      });
    }
  }

  const calibrationBuckets = buildCalibrationBuckets(outcomes);
  const shortSummary = modelSummary(outcomes, "short", SHORT_HORIZONS);
  const mediumSummary = modelSummary(outcomes, "medium", MEDIUM_HORIZONS);
  const readyPeriods = [...Object.values(shortSummary.horizons), ...Object.values(mediumSummary.horizons)].filter((row) => row.status === "ready").length;
  return {
    version: V20_MODEL_VERSION,
    generatedAt: new Date().toISOString(),
    status: readyPeriods ? "ready" : "insufficient_history",
    readiness: readyPeriods === SHORT_HORIZONS.length + MEDIUM_HORIZONS.length ? "complete" : readyPeriods ? "partial" : "accumulating",
    noLookAhead: true,
    methodology: {
      split: "expanding_walk_forward",
      minimumTrainingSessions,
      testStepSessions,
      entry: "next_trading_day_open",
      sameBarConflict: "stop_first",
      probability: "beta_2_2_then_isotonic",
      costs: executionCosts({ group: "listed", ...costOverrides }),
      pointInTime: "price, financial, revenue, institutional, risk, and context rows are filtered by availability date",
    },
    models: { short: shortSummary, medium: mediumSummary },
    outcomes,
    calibrationBuckets,
  };
}

export const v20BacktestInternals = {
  quantile,
  poolAdjacentViolators,
  returnsWithCosts,
  evaluatePath,
  stockAsOf,
  contextAsOf,
  riskAsOf,
  researchEligible,
  lockedLimitUp,
  lockedLimitDown,
};
