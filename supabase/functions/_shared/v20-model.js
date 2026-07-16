const SHORT_WEIGHTS = Object.freeze({
  technicalTrend: 20,
  volumePrice: 20,
  institutional: 15,
  market: 15,
  industry: 10,
  news: 10,
  fundamentalSafety: 5,
  liquidity: 5,
});

const MEDIUM_WEIGHTS = Object.freeze({
  growthEarnings: 25,
  industryTrend: 20,
  institutional: 15,
  mediumTechnical: 15,
  valuation: 10,
  financialSafety: 10,
  news: 5,
});

export const V20_MODEL_VERSION = "20.0";
export const V20_HORIZONS = Object.freeze({ short: [2, 3, 5, 10], medium: [20, 40, 60] });

const finite = (value) => value !== null && value !== undefined && Number.isFinite(Number(value));
const number = (value, fallback = null) => finite(value) ? Number(value) : fallback;
const clamp = (value, low = 0, high = 100) => Math.max(low, Math.min(high, Number(value)));
const round = (value, digits = 4) => finite(value) ? Number(Number(value).toFixed(digits)) : null;
const mean = (values) => {
  const usable = values.filter(finite).map(Number);
  return usable.length ? usable.reduce((sum, value) => sum + value, 0) / usable.length : null;
};
const scale = (value, low, high) => !finite(value) ? null
  : clamp((Number(value) - low) / Math.max(0.000001, high - low) * 100);
const weightedScore = (values, weights) => round(Object.entries(weights).reduce(
  (total, [key, weight]) => total + (finite(values[key]) ? clamp(values[key]) : 50) * weight,
  0,
) / Object.values(weights).reduce((total, weight) => total + weight, 0), 2);

function resultCategories(row) {
  return Array.isArray(row?.result?.categories) ? row.result.categories : [];
}

function categoryScore(row, ...keys) {
  return mean(resultCategories(row)
    .filter((entry) => keys.includes(String(entry?.key || "")))
    .map((entry) => entry?.score));
}

function factorScore(row, ...keys) {
  return mean(resultCategories(row)
    .flatMap((entry) => Array.isArray(entry?.items) ? entry.items : [])
    .filter((entry) => keys.includes(String(entry?.key || "")))
    .map((entry) => entry?.score));
}

function groupFor(row) {
  if (row?.group_name === "etf" || String(row?.stock?.instrumentType || "").toUpperCase().includes("ETF")) return "etf";
  return row?.group_name === "otc" ? "otc" : "listed";
}

function newsScoreFor(symbol, newsRows) {
  const matching = (Array.isArray(newsRows) ? newsRows : []).filter((item) =>
    Array.isArray(item?.symbols) && item.symbols.map(String).includes(String(symbol)));
  if (!matching.length) return { score: 50, available: false, positive: false, negative: false };
  const sentiment = mean(matching.map((item) => item.sentiment_score)) ?? 0;
  return {
    score: clamp(50 + sentiment / 2),
    available: true,
    positive: sentiment >= 20,
    negative: sentiment <= -20,
  };
}

function liquidityScore(stock, group) {
  const value = number(stock?.value);
  const volume = number(stock?.volume);
  const valueFloor = group === "otc" ? 10_000_000 : 20_000_000;
  const valueScore = value && value > 0
    ? clamp(45 + Math.log10(value / valueFloor) * 28)
    : null;
  const volumeFloor = group === "etf" ? 500 : group === "otc" ? 100 : 300;
  const volumeScore = volume && volume > 0
    ? clamp(45 + Math.log10(volume / volumeFloor) * 25)
    : null;
  return mean([valueScore, volumeScore]);
}

function mediumTechnicalScore(price) {
  const last = number(price?.lastClose);
  const ma20 = number(price?.ma20);
  const ma60 = number(price?.ma60);
  const ma120 = number(price?.ma120);
  const checks = [
    last !== null && ma20 !== null ? (last > ma20 ? 100 : 20) : null,
    last !== null && ma60 !== null ? (last > ma60 ? 100 : 15) : null,
    ma20 !== null && ma60 !== null && ma120 !== null ? (ma20 > ma60 && ma60 > ma120 ? 100 : 35) : null,
    finite(price?.ma60Slope5) ? clamp(50 + Number(price.ma60Slope5) * 12) : null,
    finite(price?.relative60) ? clamp(50 + Number(price.relative60) * 3) : null,
  ];
  return mean(checks);
}

function financialSafetyScore(financial) {
  const debt = finite(financial?.debtRatio) ? clamp(100 - Number(financial.debtRatio)) : null;
  const margin = finite(financial?.operatingMargin) ? clamp(50 + Number(financial.operatingMargin) * 3) : null;
  const cash = finite(financial?.ttmOperatingCashFlow)
    ? (Number(financial.ttmOperatingCashFlow) > 0 ? 85 : 20)
    : null;
  const inventory = finite(financial?.inventoryYoy) && finite(financial?.revenueYoy)
    ? (Number(financial.inventoryYoy) <= Number(financial.revenueYoy) + 20 ? 80 : 25)
    : null;
  const receivables = finite(financial?.receivablesYoy) && finite(financial?.revenueYoy)
    ? (Number(financial.receivablesYoy) <= Number(financial.revenueYoy) + 20 ? 80 : 25)
    : null;
  return mean([debt, margin, cash, inventory, receivables]);
}

function shortRiskScore(row, liquidity, news, marketContext) {
  const price = row?.analysis?.price || {};
  const risk = row?.result?.risk || {};
  const volatilityGap = mean([
    finite(price.atrPct) ? scale(price.atrPct, 1, 10) : null,
    price.jumpAnomaly ? 100 : 0,
    finite(price.limitUpStreak) ? clamp(Number(price.limitUpStreak) * 35) : null,
  ]);
  const overheat = mean([
    finite(price.distanceMa20) ? scale(Math.abs(Number(price.distanceMa20)), 2, 25) : null,
    finite(price.rsi14) ? scale(price.rsi14, 55, 85) : null,
  ]);
  const institutional = categoryScore(row, "chip");
  const values = {
    volatilityGap,
    liquidity: finite(liquidity) ? 100 - liquidity : 50,
    overheat,
    chipReversal: finite(institutional) ? 100 - institutional : 50,
    market: clamp(50 - Number(marketContext?.regime_score || 0) / 2),
    companyEvent: mean([news.negative ? 90 : 35, clamp(Number(risk.deduction || 0) * 4)]),
    restrictions: risk.hardExcluded ? 100 : 0,
  };
  return weightedScore(values, {
    volatilityGap: 20,
    liquidity: 15,
    overheat: 15,
    chipReversal: 15,
    market: 15,
    companyEvent: 10,
    restrictions: 10,
  });
}

function mediumRiskScore(row, news, marketContext) {
  const price = row?.analysis?.price || {};
  const financial = row?.analysis?.financial || {};
  const revenue = row?.analysis?.revenue || {};
  const valuation = categoryScore(row, "valuation");
  const values = {
    volatility: finite(price.atrPct) ? scale(price.atrPct, 1, 10) : 50,
    financial: finite(financial.debtRatio) ? scale(financial.debtRatio, 30, 90) : 50,
    growth: finite(revenue.acceleration3) ? clamp(50 - Number(revenue.acceleration3) * 5) : 50,
    valuation: finite(valuation) ? 100 - valuation : 50,
    trend: finite(price.ma60Slope5) ? clamp(50 - Number(price.ma60Slope5) * 12) : 50,
    marketEvent: mean([clamp(50 - Number(marketContext?.regime_score || 0) / 2), news.negative ? 90 : 35]),
  };
  return weightedScore(values, { volatility: 25, financial: 20, growth: 15, valuation: 15, trend: 15, marketEvent: 10 });
}

function shortStrategy(row, news) {
  const price = row?.analysis?.price || {};
  const institutional = row?.analysis?.institutional || {};
  if (price.breakout20 && Number(price.volumeRatio || 0) >= 1.2) return "momentum_breakout";
  if (news.positive) return "event_catalyst";
  if (Number(institutional.inst20 || 0) > 0 && Number(institutional.intensity5 || 0) > 0) return "institutional_flow";
  if (Number(price.rsi14 || 50) < 35 && Number(price.distanceMa60 || 0) >= -8) return "oversold_rebound";
  return "trend_pullback";
}

function mediumStrategy(row) {
  const price = row?.analysis?.price || {};
  const revenue = row?.analysis?.revenue || {};
  const institutional = row?.analysis?.institutional || {};
  const valuation = categoryScore(row, "valuation") || 0;
  if (Number(revenue.acceleration3 || 0) > 3 && Number(revenue.avg3Yoy || 0) > 5) return "growth_momentum";
  if (Number(institutional.inst20 || 0) > 0) return "institutional_positioning";
  if (price.breakout20 && Number(price.ma60Slope5 || 0) > 0) return "medium_breakout";
  if (valuation >= 70 && Number(price.relative60 || 0) >= -5) return "value_recovery";
  if (Number(revenue.yoy || 0) > 0 && Number(revenue.acceleration3 || 0) > 0) return "cyclical_recovery";
  return "industry_trend";
}

function calibrationFor(buckets, modelKey, strategyKey, horizon, regime, score) {
  const decile = Math.max(0, Math.min(9, Math.floor(Number(score || 0) / 10)));
  const rows = Array.isArray(buckets) ? buckets : [];
  return rows.find((row) => row.model_key === modelKey && row.strategy_key === strategyKey &&
      Number(row.horizon_days) === horizon && row.market_regime === regime &&
      Number(row.score_decile) === decile && Number(row.sample_count) >= 60)
    || rows.find((row) => row.model_key === modelKey && row.strategy_key === "all" &&
      Number(row.horizon_days) === horizon && row.market_regime === regime &&
      Number(row.score_decile) === -1 && Number(row.sample_count) >= 150)
    || null;
}

function prediction({ modelKey, strategyKey, horizon, score, risk, price, group, marketContext, buckets }) {
  const regime = String(marketContext?.regime || "sideways");
  const calibration = calibrationFor(buckets, modelKey, strategyKey, horizon, regime, score);
  if (calibration) {
    return {
      basis: "walk-forward-calibration",
      upProbability: number(calibration.calibrated_probability),
      expectedReturnNet: number(calibration.average_net_return),
      returnP10: number(calibration.return_p10),
      returnP50: number(calibration.return_p50),
      returnP90: number(calibration.return_p90),
      mfe: number(calibration.average_mfe),
      mae: number(calibration.average_mae),
      targetFirstProbability: number(calibration.target_first_probability),
    };
  }
  const probability = clamp(50 + (score - 50) * 0.38 - (risk - 50) * 0.18 + Number(marketContext?.regime_score || 0) * 0.03, 25, 78);
  const atrPct = Math.max(0.5, number(price?.atrPct, 3));
  const scaleByHorizon = Math.sqrt(horizon / (modelKey === "short" ? 5 : 20));
  const gross = ((probability / 100) * 0.9 - (1 - probability / 100) * 0.7) * atrPct * scaleByHorizon;
  const roundTripCost = group === "etf" ? 0.685 : 0.885;
  const median = gross - roundTripCost;
  return {
    basis: "deterministic-quant-rule-v20-bootstrap",
    upProbability: round(probability, 2),
    expectedReturnNet: round(median, 4),
    returnP10: round(median - atrPct * scaleByHorizon * 1.3, 4),
    returnP50: round(median, 4),
    returnP90: round(median + atrPct * scaleByHorizon * 1.5, 4),
    mfe: round(Math.max(0, atrPct * scaleByHorizon * 1.4), 4),
    mae: round(-atrPct * scaleByHorizon, 4),
    targetFirstProbability: round(clamp(probability - risk * 0.08), 2),
  };
}

function levels(modelKey, price) {
  const close = number(price?.lastClose);
  if (!close || close <= 0) return {};
  const atr = Math.max(close * 0.005, number(price?.atr14, close * 0.03));
  const support = modelKey === "short"
    ? number(price?.ma20, close - atr)
    : number(price?.ma60, number(price?.ma20, close - atr));
  const entry = Math.min(close, support + atr * (modelKey === "short" ? 0.5 : 0.8));
  const stopA = support - atr * (modelKey === "short" ? 0.3 : 0.6);
  const stopB = entry - atr * (modelKey === "short" ? 1.5 : 2);
  const stop = Math.max(0.01, Math.max(stopA, stopB));
  const oneR = Math.max(atr, entry - stop);
  return {
    entryLow: round(Math.max(0.01, entry - atr * 0.25), 2),
    entryHigh: round(entry + atr * 0.25, 2),
    breakoutPrice: round(number(price?.high20, close + atr), 2),
    noChasePrice: round(Math.max(close, number(price?.high20, close)) + atr * 0.3, 2),
    stopLoss: round(stop, 2),
    takeProfit1: round(entry + oneR, 2),
    takeProfit2: round(entry + oneR * 2, 2),
    riskRewardRatio: round((oneR * 2) / Math.max(0.01, entry - stop), 2),
  };
}

function sourceDates(row, marketContext) {
  return {
    price: row?.stock?.priceDate || row?.analysis?.price?.lastDate || row?.data_date || null,
    revenue: row?.analysis?.revenue?.availableAt || null,
    financial: row?.analysis?.financial?.availableAt || null,
    institutional: row?.analysis?.institutional?.date || null,
    holdings: row?.analysis?.holdings?.date || null,
    market: marketContext?.data_date || row?.data_date || null,
  };
}

function completenessFor(row, modelKey, news) {
  const price = row?.analysis?.price || {};
  const revenue = row?.analysis?.revenue || {};
  const financial = row?.analysis?.financial || {};
  const institutional = row?.analysis?.institutional || {};
  const checks = modelKey === "short"
    ? [price.rows >= 120, finite(price.atrPct), finite(price.volumeRatio), finite(institutional.days), finite(row?.stock?.value), news.available]
    : [price.rows >= 120, finite(price.ma60), finite(price.ma120), finite(revenue.months), finite(financial.quarters), finite(institutional.days), news.available];
  return round(checks.filter(Boolean).length / checks.length * 100, 2);
}

function gatesFor({ row, modelKey, strategyKey, score, risk, completeness, predictionResult, levelsResult, marketContext, news }) {
  const price = row?.analysis?.price || {};
  const stock = row?.stock || {};
  const resultRisk = row?.result?.risk || {};
  const group = groupFor(row);
  const valueFloor = group === "otc" ? 10_000_000 : 20_000_000;
  const volumeFloor = group === "etf" ? 500 : group === "otc" ? 100 : 300;
  const trend = modelKey === "short"
    ? strategyKey === "oversold_rebound"
      ? Number(price.rsi14 || 100) < 40 && Number(price.distanceMa60 || -100) > -10
      : Number(price.lastClose || 0) > Number(price.ma20 || Infinity) && Number(price.ma20Slope5 || 0) >= 0
    : Number(price.lastClose || 0) > Number(price.ma60 || Infinity) && Number(price.ma60Slope5 || 0) >= 0;
  const relative = modelKey === "short" ? Number(price.relative20 || -100) >= 0 : Number(price.relative60 || -100) >= 0;
  const supportScore = modelKey === "short"
    ? Math.max(categoryScore(row, "growth") || 0, categoryScore(row, "chip") || 0, news.score)
    : Math.max(categoryScore(row, "growth") || 0, categoryScore(row, "chip") || 0, news.score);
  const gates = {
    data_complete: completeness >= 60 && price.sufficient === true,
    tradeable_liquid: !resultRisk.hardExcluded && Number(stock.value || 0) >= valueFloor && Number(stock.volume || 0) >= volumeFloor,
    market_allowed: !["strong_bear"].includes(String(marketContext?.regime || "sideways")),
    trend_structure: trend,
    relative_strength: relative,
    evidence_support: supportScore >= 55,
    positive_expectancy: Number(predictionResult.expectedReturnNet || -999) > 0 && Number(levelsResult.riskRewardRatio || 0) >= 1.3,
  };
  return {
    passed: Object.values(gates).every(Boolean) && score >= 60 && risk <= 75,
    values: gates,
  };
}

function actionFor(modelKey, gates, score, risk, price) {
  if (!gates.values.data_complete) return "資料不足";
  if (risk >= 80 || !gates.values.tradeable_liquid) return "風險過高";
  if (Number(price?.distanceMa20 || 0) > 15) return "不宜追價";
  if (modelKey === "short") {
    if (gates.passed && score >= 75) return "可以布局";
    if (!gates.values.trend_structure) return "等待突破";
    if (score >= 60) return "等待拉回";
    return "觀察";
  }
  if (gates.passed && score >= 75) return "適合布局";
  if (!gates.values.trend_structure) return "等待趨勢確認";
  if (score >= 60) return "等待回檔";
  return "成長降溫";
}

function reasonList(row, modelKey, strategyKey) {
  const base = Array.isArray(row?.result?.reasons) ? row.result.reasons : [];
  const strategyReason = modelKey === "short"
    ? `短期策略：${strategyKey}`
    : `中期類型：${strategyKey}`;
  return [...new Set([strategyReason, ...base])].slice(0, 5);
}

function invalidationList(modelKey) {
  return modelKey === "short"
    ? ["跌破停損價", "突破後兩日跌回原平台", "五日內量價與籌碼沒有延續", "事件題材失去市場反應"]
    : ["營收或 EPS 成長明顯減速", "毛利率持續下降", "法人轉為大量賣超", "跌破中期支撐或 60 日線", "產業需求或政策反轉"];
}

/**
 * @param {any} row
 * @param {{marketContext?: any, newsRows?: any[], calibrationBuckets?: any[]}} [options]
 */
export function scoreCacheRow(row, options = {}) {
  const { marketContext = {}, newsRows = [], calibrationBuckets = [] } = options;
  const group = groupFor(row);
  const news = newsScoreFor(row?.symbol, newsRows);
  const price = row?.analysis?.price || {};
  const liquidity = liquidityScore(row?.stock || {}, group);
  const shortFeatures = {
    technicalTrend: categoryScore(row, "technical", "trend"),
    volumePrice: factorScore(row, "volume", "volume_structure", "breakout", "relative20"),
    institutional: group === "etf" ? 50 : categoryScore(row, "chip"),
    market: categoryScore(row, "market"),
    industry: factorScore(row, "industry_breadth", "industry_change", "relative20"),
    news: news.score,
    fundamentalSafety: mean([categoryScore(row, "growth"), categoryScore(row, "valuation", "structure", "tracking")]),
    liquidity,
  };
  const mediumFeatures = {
    growthEarnings: group === "etf" ? categoryScore(row, "tracking", "structure") : categoryScore(row, "growth"),
    industryTrend: mean([categoryScore(row, "market"), factorScore(row, "industry_breadth", "industry_change"), finite(price.relative60) ? clamp(50 + Number(price.relative60) * 3) : null]),
    institutional: group === "etf" ? 50 : categoryScore(row, "chip"),
    mediumTechnical: mediumTechnicalScore(price),
    valuation: categoryScore(row, "valuation", "tracking"),
    financialSafety: group === "etf" ? categoryScore(row, "structure", "liquidity") : financialSafetyScore(row?.analysis?.financial || {}),
    news: news.score,
  };
  const models = [
    { key: "short", features: shortFeatures, weights: SHORT_WEIGHTS, strategy: shortStrategy(row, news) },
    { key: "medium", features: mediumFeatures, weights: MEDIUM_WEIGHTS, strategy: mediumStrategy(row) },
  ];
  const signalDate = row?.data_date || row?.stock?.priceDate || price.lastDate;
  const signals = [];
  let eligibleShort = false;
  let eligibleMedium = false;

  for (const model of models) {
    const score = weightedScore(model.features, model.weights);
    const risk = model.key === "short"
      ? shortRiskScore(row, liquidity, news, marketContext)
      : mediumRiskScore(row, news, marketContext);
    const completeness = completenessFor(row, model.key, news);
    const confidence = round(Math.min(number(row?.confidence, 0), completeness), 2);
    const modelLevels = levels(model.key, price);
    for (const horizon of V20_HORIZONS[model.key]) {
      const predictionResult = prediction({
        modelKey: model.key,
        strategyKey: model.strategy,
        horizon,
        score,
        risk,
        price,
        group,
        marketContext,
        buckets: calibrationBuckets,
      });
      const gates = gatesFor({
        row,
        modelKey: model.key,
        strategyKey: model.strategy,
        score,
        risk,
        completeness,
        predictionResult,
        levelsResult: modelLevels,
        marketContext,
        news,
      });
      const official = gates.passed && confidence >= 65;
      if (model.key === "short") eligibleShort ||= gates.values.data_complete && gates.values.tradeable_liquid;
      else eligibleMedium ||= gates.values.data_complete && gates.values.tradeable_liquid;
      signals.push({
        symbol: String(row.symbol),
        signal_date: signalDate,
        model_key: model.key,
        horizon_days: horizon,
        model_version: V20_MODEL_VERSION,
        group_name: group,
        name: String(row?.stock?.name || row?.symbol || ""),
        market: row?.stock?.market || row?.analysis?.market || null,
        industry: row?.stock?.industry || null,
        instrument_type: row?.stock?.instrumentType || row?.analysis?.instrumentType || null,
        strategy_key: model.strategy,
        opportunity_score: score,
        risk_score: risk,
        confidence,
        completeness,
        official,
        gate_passed: gates.passed,
        gate_results: { ...gates.values, probabilityBasis: predictionResult.basis },
        feature_scores: model.features,
        prediction_basis: predictionResult.basis,
        up_probability: predictionResult.upProbability,
        expected_return_net: predictionResult.expectedReturnNet,
        return_p10: predictionResult.returnP10,
        return_p50: predictionResult.returnP50,
        return_p90: predictionResult.returnP90,
        mfe: predictionResult.mfe,
        mae: predictionResult.mae,
        target_first_probability: predictionResult.targetFirstProbability,
        entry_low: modelLevels.entryLow || null,
        entry_high: modelLevels.entryHigh || null,
        breakout_price: modelLevels.breakoutPrice || null,
        no_chase_price: modelLevels.noChasePrice || null,
        stop_loss: modelLevels.stopLoss || null,
        take_profit_1: modelLevels.takeProfit1 || null,
        take_profit_2: modelLevels.takeProfit2 || null,
        risk_reward_ratio: modelLevels.riskRewardRatio || null,
        expected_value: predictionResult.expectedReturnNet,
        recommended_holding_days: horizon,
        recommended_action: actionFor(model.key, gates, score, risk, price),
        reasons: reasonList(row, model.key, model.strategy),
        risks: [...new Set([...(row?.result?.risk?.flags || []), ...(row?.result?.risk?.hardReasons || [])])].slice(0, 6),
        invalidation_conditions: invalidationList(model.key),
        source_dates: sourceDates(row, marketContext),
      });
    }
  }
  return {
    signals,
    universe: {
      symbol: String(row.symbol),
      as_of_date: signalDate,
      model_version: V20_MODEL_VERSION,
      group_name: group,
      name: String(row?.stock?.name || row?.symbol || ""),
      market: row?.stock?.market || row?.analysis?.market || null,
      industry: row?.stock?.industry || null,
      instrument_type: row?.stock?.instrumentType || row?.analysis?.instrumentType || null,
      active: true,
      eligible_short: eligibleShort,
      eligible_medium: eligibleMedium,
      inclusion_reasons: ["v20-point-in-time-cache"],
      exclusion_reasons: [...new Set(row?.result?.risk?.hardReasons || [])],
      source_dates: sourceDates(row, marketContext),
    },
  };
}

function marketGroup(row) {
  if (String(row?.instrument_type || "").toUpperCase().includes("ETF")) return "etf";
  const market = String(row?.market || "").toLowerCase();
  return market.includes("櫃") || market.includes("otc") ? "otc" : "listed";
}

function groupBreadth(rows) {
  const changes = rows.map((row) => number(row?.change_pct)).filter(finite);
  const advancing = changes.filter((value) => value > 0).length;
  const declining = changes.filter((value) => value < 0).length;
  const flat = changes.length - advancing - declining;
  return {
    count: changes.length,
    advancing,
    declining,
    flat,
    advanceRatio: changes.length ? round(advancing / changes.length * 100, 2) : null,
    averageChange: round(mean(changes), 4),
    turnover: round(rows.reduce((sum, row) => sum + Number(row?.trade_value || 0), 0), 0),
  };
}

export function buildMarketContext(snapshotRows, dataDate, globalContext = {}) {
  const rows = Array.isArray(snapshotRows) ? snapshotRows : [];
  const listed = rows.filter((row) => marketGroup(row) === "listed");
  const otc = rows.filter((row) => marketGroup(row) === "otc");
  const etf = rows.filter((row) => marketGroup(row) === "etf");
  const allStocks = [...listed, ...otc];
  const breadth = groupBreadth(allStocks);
  const listedBreadth = groupBreadth(listed);
  const otcBreadth = groupBreadth(otc);
  const etfBreadth = groupBreadth(etf);
  const trendScore = clamp((number(breadth.averageChange, 0)) * 20, -100, 100);
  const breadthScore = finite(breadth.advanceRatio) ? clamp((breadth.advanceRatio - 50) * 4, -100, 100) : 0;
  const totalVolume = rows.reduce((sum, row) => sum + Math.abs(Number(row?.volume || 0)), 0);
  const institutionalNet = rows.reduce((sum, row) => sum + Number(row?.institutional_buy || 0), 0);
  const institutionalScore = totalVolume ? clamp(Math.tanh(institutionalNet / totalVolume * 20) * 100, -100, 100) : 0;
  const turnoverScore = 0;
  const globalScore = clamp(number(globalContext?.score, 0), -100, 100);
  const regimeScore = round(
    trendScore * 0.35 + breadthScore * 0.20 + turnoverScore * 0.15 +
      institutionalScore * 0.15 + globalScore * 0.15,
    2,
  );
  const regime = regimeScore >= 60 ? "strong_bull"
    : regimeScore >= 25 ? "bull"
    : regimeScore <= -60 ? "strong_bear"
    : regimeScore <= -25 ? "bear"
    : "sideways";
  const degraded = [
    "taiex_official_index",
    "tpex_official_index",
    "tx_futures",
    ...(globalContext?.available ? [] : ["international_context"]),
  ];
  const completeness = clamp(100 - degraded.length * 12.5);
  return {
    data_date: dataDate,
    model_version: V20_MODEL_VERSION,
    regime,
    regime_score: regimeScore,
    confidence: round(Math.min(90, completeness), 2),
    completeness: round(completeness, 2),
    status: rows.length ? "partial" : "error",
    taiex: { ...listedBreadth, basis: "listed-market-breadth-proxy" },
    tpex: { ...otcBreadth, basis: "otc-market-breadth-proxy" },
    tx_futures: {},
    breadth: { all: breadth, listed: listedBreadth, otc: otcBreadth, etf: etfBreadth },
    institutional: { net: round(institutionalNet, 3), score: round(institutionalScore, 2) },
    global_context: globalContext || {},
    source_dates: { snapshots: dataDate, global: globalContext?.dataDate || null },
    degraded_sources: degraded,
    fetched_at: new Date().toISOString(),
  };
}

export const v20ModelInternals = {
  SHORT_WEIGHTS,
  MEDIUM_WEIGHTS,
  categoryScore,
  factorScore,
  liquidityScore,
  calibrationFor,
  groupBreadth,
};
