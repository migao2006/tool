import {
  MEDIUM_HORIZONS,
  MEDIUM_RESEARCH_HORIZONS,
  MEDIUM_WEIGHTS,
  SHORT_HORIZONS,
  SHORT_WEIGHTS,
  V20_COST_POLICY_VERSION,
  V20_MODEL_VERSION,
  adjustOpportunityScore,
  estimateExecutionCosts,
} from "../supabase/functions/_shared/v20-opportunity-policy.js";

export {
  MEDIUM_HORIZONS,
  MEDIUM_RESEARCH_HORIZONS,
  MEDIUM_WEIGHTS,
  SHORT_HORIZONS,
  SHORT_WEIGHTS,
  V20_COST_POLICY_VERSION,
  V20_MODEL_VERSION,
  adjustOpportunityScore,
  estimateExecutionCosts,
};

const finite = (value) => value !== null && value !== undefined && Number.isFinite(Number(value));
const clamp = (value, low = 0, high = 100) => Math.max(low, Math.min(high, Number(value)));
const round = (value, digits = 2) => finite(value) ? Number(Number(value).toFixed(digits)) : null;
const mean = (values) => {
  const usable = values.filter(finite).map(Number);
  return usable.length ? usable.reduce((sum, value) => sum + value, 0) / usable.length : null;
};
const sum = (values) => values.filter(finite).reduce((total, value) => total + Number(value), 0);

export const SHORT_RISK_WEIGHTS = Object.freeze({
  volatilityGap: 20,
  liquidity: 15,
  overheat: 15,
  chipReversal: 15,
  systemicMarket: 15,
  companyEvent: 10,
  tradingRestrictions: 10,
});

export const MEDIUM_RISK_WEIGHTS = Object.freeze({
  growthDeterioration: 25,
  trendBreakdown: 20,
  valuationExcess: 15,
  institutionalReversal: 15,
  industryReversal: 15,
  financialEvent: 10,
});

function interpolate(value, points) {
  if (!finite(value) || !Array.isArray(points) || points.length < 2) return null;
  const sorted = [...points].sort((a, b) => a[0] - b[0]);
  const numeric = Number(value);
  if (numeric <= sorted[0][0]) return clamp(sorted[0][1]);
  if (numeric >= sorted.at(-1)[0]) return clamp(sorted.at(-1)[1]);
  for (let index = 1; index < sorted.length; index += 1) {
    const [rightX, rightY] = sorted[index];
    const [leftX, leftY] = sorted[index - 1];
    if (numeric <= rightX) {
      const ratio = (numeric - leftX) / (rightX - leftX);
      return clamp(leftY + ratio * (rightY - leftY));
    }
  }
  return null;
}

function normalizedRegime(value) {
  const key = String(value || "").trim().toLowerCase().replace(/[ -]/g, "_");
  const aliases = {
    strong_bull: "strong_bull", strong_bullish: "strong_bull", 強勢多頭: "strong_bull",
    bull: "bull", bullish: "bull", 偏多: "bull",
    sideways: "sideways", range: "sideways", neutral: "sideways", 震盪: "sideways",
    bear: "bear", bearish: "bear", 偏空: "bear",
    strong_bear: "strong_bear", strong_bearish: "strong_bear", 強勢空頭: "strong_bear",
  };
  return aliases[key] || null;
}

function groupOf(stock, deep) {
  if (String(stock?.instrumentType || deep?.instrumentType || "").toUpperCase() === "ETF") return "etf";
  const market = String(stock?.market || "").toLowerCase();
  if (["otc", "tpex", "上櫃"].some((key) => market.includes(key))) return "otc";
  return "listed";
}

function scoreFactor(key, label, value, score, weight = 1, source = null) {
  return {
    key,
    label,
    value: typeof value === "boolean" || finite(value) || typeof value === "string" ? value : null,
    score: finite(score) ? round(clamp(score), 1) : null,
    weight,
    source,
  };
}

function scoreComponent(key, label, weight, factors) {
  const expected = sum(factors.map((row) => row.weight));
  const usable = factors.filter((row) => finite(row.score));
  const available = sum(usable.map((row) => row.weight));
  return {
    key,
    label,
    weight,
    score: available ? round(sum(usable.map((row) => row.score * row.weight)) / available, 1) : null,
    coverage: expected ? round(available / expected * 100, 1) : 0,
    factors,
  };
}

function aggregate(components, minimumCoverage = 60) {
  const completeness = round(sum(components.map((row) => row.weight * row.coverage / 100)), 1);
  const usable = components.filter((row) => finite(row.score));
  const weight = sum(usable.map((row) => row.weight));
  const score = completeness >= minimumCoverage && weight
    ? round(sum(usable.map((row) => row.score * row.weight)) / weight, 1)
    : null;
  return { score, dataCompleteness: completeness };
}

function cumulative(history, key, period) {
  if (!Array.isArray(history) || history.length < period) return null;
  const values = history.slice(-period).map((row) => row?.[key]);
  return values.every(finite) ? sum(values) : null;
}

function latestPrice(stock, deep) {
  return finite(deep?.price?.lastClose) ? Number(deep.price.lastClose)
    : finite(stock?.close) ? Number(stock.close)
      : finite(deep?.priceHistory?.at(-1)?.close) ? Number(deep.priceHistory.at(-1).close) : null;
}

function supportFromHistory(history, period) {
  const rows = Array.isArray(history) ? history.slice(-period) : [];
  const values = rows.map((row) => row?.low).filter(finite).map(Number);
  return values.length === period ? Math.min(...values) : null;
}

function priorHighFromHistory(history, period) {
  const rows = Array.isArray(history) ? history.slice(-(period + 1), -1) : [];
  const values = rows.map((row) => row?.high).filter(finite).map(Number);
  return values.length === period ? Math.max(...values) : null;
}

function shortStyle(deep, context) {
  const price = deep?.price || {};
  const institutional = deep?.institutional || {};
  const catalyst = context?.newsEventScore ?? context?.catalystScore;
  if (price.breakout20 === true && finite(price.volumeRatio) && price.volumeRatio >= 1.3 && finite(price.relative20) && price.relative20 > 0) return "momentum_breakout";
  if (finite(price.ma20) && finite(price.ma60) && price.ma20 > price.ma60 && finite(price.distanceMa20) && price.distanceMa20 >= -3 && price.distanceMa20 <= 5) return "trend_pullback";
  if ((finite(institutional.inst20) && institutional.inst20 > 0) || institutional.foreignStreak >= 3 || institutional.trustStreak >= 3) return "institutional_flow";
  if (finite(catalyst) && catalyst >= 65) return "event_catalyst";
  if (finite(price.rsi14) && price.rsi14 <= 40 && finite(price.return5) && price.return5 > 0) return "oversold_rebound";
  return null;
}

function mediumStyle(deep, context) {
  const revenue = deep?.revenue || {};
  const financial = deep?.financial || {};
  const institutional = deep?.institutional || {};
  const price = deep?.price || {};
  if (finite(revenue.acceleration3) && revenue.acceleration3 > 2 && (finite(financial.epsYoy) ? financial.epsYoy > 0 : finite(revenue.avg3Yoy) && revenue.avg3Yoy > 10)) return "growth_momentum";
  if ((finite(institutional.inst20) && institutional.inst20 > 0) || (finite(institutional.trust20) && institutional.trust20 > 0)) return "institutional_accumulation";
  if (finite(context?.industryTrendScore) && context.industryTrendScore >= 70) return "industry_trend";
  if (finite(price.distanceHigh60) && price.distanceHigh60 >= -2 && finite(price.ma60Slope5) && price.ma60Slope5 > 0) return "medium_breakout";
  if (finite(context?.valuationScore) && context.valuationScore >= 70 && finite(price.ma20) && finite(price.ma60) && price.ma20 >= price.ma60) return "value_recovery";
  if (finite(revenue.yoy) && finite(revenue.acceleration3) && revenue.yoy < 10 && revenue.acceleration3 > 0) return "cycle_recovery";
  return null;
}

function shortComponents(stock, deep, context) {
  const price = deep?.price || {};
  const institutional = deep?.institutional || {};
  const margin = deep?.margin || {};
  const revenue = deep?.revenue || {};
  const marketScore = context?.marketScore;
  const industryScore = context?.industryTrendScore ?? context?.industryScore;
  const newsScore = context?.newsEventScore ?? context?.catalystScore;
  const costs = estimateExecutionCosts({
    group: groupOf(stock, deep),
    averageDailyValue: stock?.value ?? price?.averageValue20,
    atrPct: price?.atrPct,
    price: latestPrice(stock, deep),
    expectedOrderValue: context?.expectedOrderValue,
    commissionRatePerSidePct: context?.costAssumptions?.commissionRatePerSidePct,
  });
  return [
    scoreComponent("priceVolumeTrend", "價量與趨勢結構", SHORT_WEIGHTS.priceVolumeTrend, [
      scoreFactor("ma20_slope", "20 日均線方向", price.ma20Slope5, interpolate(price.ma20Slope5, [[-4, 0], [0, 45], [1, 70], [3, 100]]), 2, "price_history"),
      scoreFactor("ma_alignment", "均線結構", finite(price.lastClose) && finite(price.ma20) && finite(price.ma60) ? `${price.lastClose > price.ma20}/${price.ma20 > price.ma60}` : null, finite(price.lastClose) && finite(price.ma20) && finite(price.ma60) ? (price.lastClose > price.ma20 && price.ma20 > price.ma60 ? 100 : price.lastClose > price.ma20 ? 58 : 20) : null, 2, "price_history"),
      scoreFactor("breakout20", "20 日突破", price.breakout20, price.breakout20 == null ? null : price.breakout20 ? 100 : 45, 1.5, "price_history"),
      scoreFactor("rsi14", "RSI 動能區間", price.rsi14, interpolate(price.rsi14, [[20, 15], [35, 55], [50, 75], [62, 100], [72, 70], [85, 0]]), 1, "price_history"),
      scoreFactor("macd", "MACD 動能", price.macdHistogram, finite(price.macdHistogram) ? (price.macdHistogram > 0 ? 85 : 30) : null, 1, "price_history"),
      scoreFactor("volume_ratio", "量能變化", price.volumeRatio, interpolate(price.volumeRatio, [[0.4, 15], [0.8, 45], [1.2, 75], [1.8, 100], [3.5, 65]]), 2, "price_history"),
      scoreFactor("up_down_volume", "上漲與下跌量比", price.upDownVolumeRatio, interpolate(price.upDownVolumeRatio, [[0.4, 10], [0.8, 40], [1, 58], [1.5, 85], [2.5, 100]]), 2, "price_history"),
      scoreFactor("return5", "五日價格動能", price.return5, interpolate(price.return5, [[-12, 5], [-3, 35], [0, 55], [5, 85], [10, 100], [20, 45]]), 1, "price_history"),
    ]),
    scoreComponent("institutional", "法人籌碼", SHORT_WEIGHTS.institutional, [
      scoreFactor("inst5", "法人五日累計", institutional.inst5, interpolate(institutional.inst5, [[-20_000, 0], [-1_000, 30], [0, 50], [1_000, 70], [20_000, 100]]), 2, "institutional"),
      scoreFactor("inst_intensity", "法人買賣強度", institutional.intensity5, interpolate(institutional.intensity5, [[-8, 0], [-1, 35], [0, 50], [2, 75], [6, 100]]), 2, "institutional"),
      scoreFactor("foreign_streak", "外資連續方向", institutional.foreignStreak, interpolate(institutional.foreignStreak, [[0, 40], [2, 65], [5, 90], [8, 100]]), 1, "institutional"),
      scoreFactor("trust_streak", "投信連續方向", institutional.trustStreak, interpolate(institutional.trustStreak, [[0, 40], [2, 68], [5, 95], [8, 100]]), 1, "institutional"),
      scoreFactor("margin20", "融資二十日變化", margin.marginChange20, finite(margin.marginChange20) ? (margin.marginChange20 <= 0 ? 75 : 35) : null, 1, "margin"),
    ]),
    scoreComponent("volatilityRiskReward", "波動與風險報酬", SHORT_WEIGHTS.volatilityRiskReward, [
      scoreFactor("atr", "ATR 波動可執行性", price.atrPct, interpolate(price.atrPct, [[0.5, 60], [2, 100], [4, 80], [7, 35], [12, 0]]), 2, "price_history"),
      scoreFactor("distance_ma20", "距二十日均線", price.distanceMa20, interpolate(price.distanceMa20, [[-12, 20], [-3, 75], [2, 100], [10, 60], [20, 0]]), 2, "price_history"),
      scoreFactor("overheat", "動能未過熱", price.rsi14, interpolate(price.rsi14, [[25, 35], [45, 80], [60, 100], [72, 55], [85, 0]]), 1, "price_history"),
    ]),
    scoreComponent("marketGlobal", "市場及美股環境", SHORT_WEIGHTS.marketGlobal, [
      scoreFactor("market_score", "市場環境分數", marketScore, finite(marketScore) ? marketScore : null, 3, "market_context"),
      scoreFactor("global_score", "關聯國際市場", context?.globalSectorScore, finite(context?.globalSectorScore) ? context.globalSectorScore : null, 1, "market_context"),
    ]),
    scoreComponent("relativeIndustry", "相對強弱與產業動能", SHORT_WEIGHTS.relativeIndustry, [
      scoreFactor("relative20", "相對大盤二十日強度", price.relative20, interpolate(price.relative20, [[-15, 0], [-4, 30], [0, 55], [5, 80], [12, 100]]), 2, "price_history"),
      scoreFactor("industry", "產業趨勢", industryScore, finite(industryScore) ? industryScore : null, 2, "market_context"),
      scoreFactor("relative_percentile", "產業內相對強度百分位", context?.relativeStrengthPercentile, finite(context?.relativeStrengthPercentile) ? context.relativeStrengthPercentile : null, 1, "peer_context"),
    ]),
    scoreComponent("revenueEventCatalyst", "營收與事件催化", SHORT_WEIGHTS.revenueEventCatalyst, [
      scoreFactor("revenue", "營收趨勢", revenue.avg3Yoy ?? revenue.yoy, interpolate(revenue.avg3Yoy ?? revenue.yoy, [[-30, 0], [-10, 25], [0, 55], [15, 80], [35, 100]]), 2, "revenue"),
      scoreFactor("news_event", "可信新聞與公告影響", finite(newsScore) ? newsScore : "none", finite(newsScore) ? newsScore : 50, 3, "news_context"),
      scoreFactor("source_reliability", "來源可信度", finite(newsScore) ? context?.newsReliability : "not_applicable", finite(newsScore) && finite(context?.newsReliability) ? context.newsReliability : 50, 1, "news_context"),
    ]),
    scoreComponent("liquidityExecutionCost", "流動性與交易成本", SHORT_WEIGHTS.liquidityExecutionCost, [
      scoreFactor("value", "成交金額", stock?.value, interpolate(stock?.value, [[5_000_000, 0], [20_000_000, 50], [100_000_000, 80], [500_000_000, 100]]), 2, "market_quote"),
      scoreFactor("volume", "成交量", stock?.volume, interpolate(stock?.volume, [[100, 0], [500, 50], [2_000, 80], [10_000, 100]]), 1, "market_quote"),
      scoreFactor("estimated_cost", "預估來回交易成本", costs.totalPct, interpolate(costs.totalPct, [[0.6, 100], [0.9, 75], [1.2, 45], [1.8, 0]]), 2, "cost_policy"),
    ]),
  ];
}

function mediumComponents(stock, deep, context) {
  const price = deep?.price || {};
  const institutional = deep?.institutional || {};
  const revenue = deep?.revenue || {};
  const financial = deep?.financial || {};
  const inst60 = cumulative(institutional.history, "inst", 60);
  const costs = estimateExecutionCosts({
    group: groupOf(stock, deep),
    averageDailyValue: stock?.value ?? price?.averageValue20,
    atrPct: price?.atrPct,
    price: latestPrice(stock, deep),
    expectedOrderValue: context?.expectedOrderValue,
    commissionRatePerSidePct: context?.costAssumptions?.commissionRatePerSidePct,
  });
  return [
    scoreComponent("revenueProfitGrowth", "營收與獲利成長", MEDIUM_WEIGHTS.revenueProfitGrowth, [
      scoreFactor("revenue_yoy", "月營收年增", revenue.yoy, interpolate(revenue.yoy, [[-30, 0], [-10, 25], [0, 50], [15, 75], [35, 100]]), 2, "revenue"),
      scoreFactor("revenue_avg3", "近三月營收趨勢", revenue.avg3Yoy, interpolate(revenue.avg3Yoy, [[-30, 0], [-10, 25], [0, 50], [15, 78], [35, 100]]), 2, "revenue"),
      scoreFactor("acceleration", "營收成長加速度", revenue.acceleration3, interpolate(revenue.acceleration3, [[-15, 0], [-3, 30], [0, 52], [5, 78], [12, 100]]), 2, "revenue"),
      scoreFactor("eps", "EPS 成長", financial.epsYoy, interpolate(financial.epsYoy, [[-40, 0], [-10, 30], [0, 52], [20, 78], [50, 100]]), 2, "financial"),
      scoreFactor("margin", "毛利率變化", financial.grossMarginYoyChange ?? financial.operatingMarginYoyChange, interpolate(financial.grossMarginYoyChange ?? financial.operatingMarginYoyChange, [[-8, 0], [-2, 30], [0, 55], [3, 80], [8, 100]]), 1, "financial"),
    ]),
    scoreComponent("industryEnvironment", "產業環境", MEDIUM_WEIGHTS.industryEnvironment, [
      scoreFactor("industry", "產業中期趨勢", context?.industryTrendScore, finite(context?.industryTrendScore) ? context.industryTrendScore : null, 3, "market_context"),
      scoreFactor("industry_demand", "產業需求與報價", context?.industryDemandScore, finite(context?.industryDemandScore) ? context.industryDemandScore : null, 2, "market_context"),
      scoreFactor("relative_percentile", "產業內相對強度", context?.relativeStrengthPercentile, finite(context?.relativeStrengthPercentile) ? context.relativeStrengthPercentile : null, 1, "peer_context"),
    ]),
    scoreComponent("institutionalPositioning", "法人中期布局", MEDIUM_WEIGHTS.institutionalPositioning, [
      scoreFactor("inst20", "法人二十日累計", institutional.inst20, interpolate(institutional.inst20, [[-30_000, 0], [-2_000, 30], [0, 50], [2_000, 72], [30_000, 100]]), 2, "institutional"),
      scoreFactor("inst60", "法人六十日累計", inst60, interpolate(inst60, [[-60_000, 0], [-5_000, 30], [0, 50], [5_000, 72], [60_000, 100]]), 2, "institutional"),
      scoreFactor("foreign20", "外資二十日累計", institutional.foreign20, interpolate(institutional.foreign20, [[-30_000, 0], [-2_000, 30], [0, 50], [2_000, 72], [30_000, 100]]), 1, "institutional"),
      scoreFactor("trust20", "投信二十日累計", institutional.trust20, interpolate(institutional.trust20, [[-10_000, 0], [-1_000, 30], [0, 50], [1_000, 75], [10_000, 100]]), 1, "institutional"),
    ]),
    scoreComponent("mediumTrend", "中期趨勢", MEDIUM_WEIGHTS.mediumTrend, [
      scoreFactor("ma_structure", "二十、六十、百二十日均線", finite(price.ma20) && finite(price.ma60) && finite(price.ma120) ? `${price.ma20}/${price.ma60}/${price.ma120}` : null, finite(price.ma20) && finite(price.ma60) && finite(price.ma120) ? (price.ma20 > price.ma60 && price.ma60 > price.ma120 ? 100 : price.ma20 > price.ma60 ? 65 : 25) : null, 3, "price_history"),
      scoreFactor("ma60_slope", "六十日均線方向", price.ma60Slope5, interpolate(price.ma60Slope5, [[-4, 0], [0, 50], [1, 75], [3, 100]]), 2, "price_history"),
      scoreFactor("relative60", "六十日相對強度", price.relative60, interpolate(price.relative60, [[-20, 0], [-5, 30], [0, 55], [8, 82], [20, 100]]), 2, "price_history"),
      scoreFactor("distance_high60", "接近六十日高點", price.distanceHigh60, interpolate(price.distanceHigh60, [[-35, 10], [-15, 45], [-5, 80], [0, 100]]), 1, "price_history"),
    ]),
    scoreComponent("valuationReasonableness", "估值合理性", MEDIUM_WEIGHTS.valuationReasonableness, [
      scoreFactor("peer_pe", "同類型本益比百分位", context?.peValuePercentile, finite(context?.peValuePercentile) ? context.peValuePercentile : null, 2, "peer_context"),
      scoreFactor("peer_pb", "同類型股價淨值比百分位", context?.pbValuePercentile, finite(context?.pbValuePercentile) ? context.pbValuePercentile : null, 1, "peer_context"),
      scoreFactor("valuation", "類型調整後估值", context?.valuationScore, finite(context?.valuationScore) ? context.valuationScore : null, 2, "peer_context"),
    ]),
    scoreComponent("financialQuality", "財務品質", MEDIUM_WEIGHTS.financialQuality, [
      scoreFactor("cash", "現金流品質", financial.cashConversion, interpolate(financial.cashConversion, [[-1, 0], [0, 35], [0.7, 72], [1.2, 100]]), 2, "financial"),
      scoreFactor("debt", "負債安全", financial.debtRatio, interpolate(financial.debtRatio, [[20, 100], [50, 72], [70, 35], [90, 0]]), 2, "financial"),
      scoreFactor("inventory", "存貨風險", finite(financial.inventoryYoy) && finite(financial.revenueYoy) ? financial.inventoryYoy - financial.revenueYoy : null, interpolate(finite(financial.inventoryYoy) && finite(financial.revenueYoy) ? financial.inventoryYoy - financial.revenueYoy : null, [[-20, 100], [0, 75], [15, 45], [40, 0]]), 1, "financial"),
      scoreFactor("receivables", "應收帳款風險", finite(financial.receivablesYoy) && finite(financial.revenueYoy) ? financial.receivablesYoy - financial.revenueYoy : null, interpolate(finite(financial.receivablesYoy) && finite(financial.revenueYoy) ? financial.receivablesYoy - financial.revenueYoy : null, [[-20, 100], [0, 75], [15, 45], [40, 0]]), 1, "financial"),
    ]),
    scoreComponent("liquidityRisk", "流動性與風險", MEDIUM_WEIGHTS.liquidityRisk, [
      scoreFactor("value", "成交金額", stock?.value, interpolate(stock?.value, [[5_000_000, 0], [20_000_000, 50], [100_000_000, 80], [500_000_000, 100]]), 2, "market_quote"),
      scoreFactor("atr", "中期波動可執行性", price.atrPct, interpolate(price.atrPct, [[0.5, 65], [2, 100], [4, 80], [7, 40], [12, 0]]), 1, "price_history"),
      scoreFactor("estimated_cost", "預估來回交易成本", costs.totalPct, interpolate(costs.totalPct, [[0.6, 100], [0.9, 75], [1.2, 45], [1.8, 0]]), 2, "cost_policy"),
    ]),
  ];
}

function weightedRisk(components) {
  const completeness = round(sum(components.map((row) => row.weight * row.coverage / 100)), 1);
  const usable = components.filter((row) => finite(row.score));
  const weight = sum(usable.map((row) => row.weight));
  return {
    riskScore: completeness >= 60 && weight ? round(sum(usable.map((row) => row.score * row.weight)) / weight, 1) : null,
    riskCompleteness: completeness,
  };
}

function shortRiskComponents(stock, deep, risk, context) {
  const price = deep?.price || {};
  const institutional = deep?.institutional || {};
  const financial = deep?.financial || {};
  const group = groupOf(stock, deep);
  return [
    scoreComponent("volatilityGap", "波動與跳空風險", SHORT_RISK_WEIGHTS.volatilityGap, [
      scoreFactor("atr", "ATR 波動", price.atrPct, interpolate(price.atrPct, [[0.5, 10], [2, 25], [4, 55], [7, 85], [12, 100]]), 2, "price_history"),
      scoreFactor("jump", "異常跳空", price.jumpAnomaly, price.jumpAnomaly == null ? null : price.jumpAnomaly ? 100 : 10, 1, "price_history"),
    ]),
    scoreComponent("liquidity", "流動性風險", SHORT_RISK_WEIGHTS.liquidity, [
      scoreFactor("value", "成交金額不足", stock?.value, interpolate(stock?.value, [[5_000_000, 100], [20_000_000, 60], [100_000_000, 25], [500_000_000, 5]]), 2, "market_quote"),
      scoreFactor("volume", "成交量不足", stock?.volume, interpolate(stock?.volume, [[100, 100], [500, 65], [2_000, 30], [10_000, 5]]), 1, "market_quote"),
    ]),
    scoreComponent("overheat", "乖離與過熱風險", SHORT_RISK_WEIGHTS.overheat, [
      scoreFactor("distance", "二十日均線乖離", price.distanceMa20, interpolate(price.distanceMa20, [[-10, 25], [0, 5], [8, 30], [15, 75], [25, 100]]), 2, "price_history"),
      scoreFactor("rsi", "RSI 過熱", price.rsi14, interpolate(price.rsi14, [[25, 20], [50, 5], [65, 25], [75, 70], [85, 100]]), 1, "price_history"),
      scoreFactor("limit", "連續漲停", price.limitUpStreak, interpolate(price.limitUpStreak, [[0, 0], [1, 45], [2, 85], [3, 100]]), 1, "price_history"),
    ]),
    scoreComponent("chipReversal", "籌碼反轉風險", SHORT_RISK_WEIGHTS.chipReversal, [
      scoreFactor("inst5", "法人短線反轉", institutional.inst5, interpolate(institutional.inst5, [[-20_000, 100], [-1_000, 75], [0, 45], [1_000, 20], [20_000, 0]]), 2, "institutional"),
      scoreFactor("intensity", "法人強度", institutional.intensity5, interpolate(institutional.intensity5, [[-8, 100], [-2, 75], [0, 45], [2, 20], [6, 0]]), 1, "institutional"),
    ]),
    scoreComponent("systemicMarket", "市場系統性風險", SHORT_RISK_WEIGHTS.systemicMarket, [
      scoreFactor("market_risk", "市場風險", context?.marketRiskScore, finite(context?.marketRiskScore) ? context.marketRiskScore : finite(context?.marketScore) ? 100 - context.marketScore : null, 3, "market_context"),
    ]),
    scoreComponent("companyEvent", "公司與事件風險", SHORT_RISK_WEIGHTS.companyEvent, [
      scoreFactor("event", "事件風險", context?.eventRiskScore, finite(context?.eventRiskScore) ? context.eventRiskScore : null, 2, "news_context"),
      scoreFactor("debt", "財務異常", financial.debtRatio, interpolate(financial.debtRatio, [[20, 5], [50, 25], [70, 60], [90, 100]]), 1, "financial"),
    ]),
    scoreComponent("tradingRestrictions", "處置與交易限制", SHORT_RISK_WEIGHTS.tradingRestrictions, [
      scoreFactor("hard", "停止、全額交割或重大異常", risk?.hardExcluded, risk?.hardExcluded == null ? null : risk.hardExcluded ? 100 : 0, 3, "risk_registry"),
      scoreFactor("attention", "注意或處置", risk?.attention ?? risk?.disposition, (risk?.attention ?? risk?.disposition) == null ? null : (risk.attention ?? risk.disposition) ? 70 : 0, 1, "risk_registry"),
      scoreFactor("etf", "ETF 類型", group, group === "etf" ? 0 : 0, 0.01, "instrument"),
    ]),
  ];
}

function mediumRiskComponents(stock, deep, risk, context) {
  const price = deep?.price || {};
  const revenue = deep?.revenue || {};
  const financial = deep?.financial || {};
  const institutional = deep?.institutional || {};
  return [
    scoreComponent("growthDeterioration", "成長惡化風險", MEDIUM_RISK_WEIGHTS.growthDeterioration, [
      scoreFactor("revenue_accel", "營收成長減速", revenue.acceleration3, interpolate(revenue.acceleration3, [[-15, 100], [-5, 75], [0, 45], [5, 20], [12, 0]]), 2, "revenue"),
      scoreFactor("margin", "獲利率下降", financial.grossMarginYoyChange ?? financial.operatingMarginYoyChange, interpolate(financial.grossMarginYoyChange ?? financial.operatingMarginYoyChange, [[-8, 100], [-3, 75], [0, 35], [3, 10]]), 1, "financial"),
    ]),
    scoreComponent("trendBreakdown", "中期趨勢破壞風險", MEDIUM_RISK_WEIGHTS.trendBreakdown, [
      scoreFactor("below60", "跌破六十日線", finite(price.lastClose) && finite(price.ma60) ? price.lastClose < price.ma60 : null, finite(price.lastClose) && finite(price.ma60) ? (price.lastClose < price.ma60 ? 85 : 10) : null, 2, "price_history"),
      scoreFactor("slope60", "六十日均線下彎", price.ma60Slope5, interpolate(price.ma60Slope5, [[-4, 100], [-1, 75], [0, 45], [1, 20], [3, 0]]), 1, "price_history"),
    ]),
    scoreComponent("valuationExcess", "估值過高風險", MEDIUM_RISK_WEIGHTS.valuationExcess, [
      scoreFactor("valuation", "類型調整估值風險", context?.valuationRiskScore, finite(context?.valuationRiskScore) ? context.valuationRiskScore : finite(context?.valuationScore) ? 100 - context.valuationScore : null, 2, "peer_context"),
      scoreFactor("distance", "中期價格乖離", price.distanceMa60, interpolate(price.distanceMa60, [[-15, 25], [0, 5], [12, 40], [25, 80], [40, 100]]), 1, "price_history"),
    ]),
    scoreComponent("institutionalReversal", "法人布局反轉風險", MEDIUM_RISK_WEIGHTS.institutionalReversal, [
      scoreFactor("inst20", "法人二十日方向", institutional.inst20, interpolate(institutional.inst20, [[-30_000, 100], [-2_000, 75], [0, 45], [2_000, 20], [30_000, 0]]), 2, "institutional"),
    ]),
    scoreComponent("industryReversal", "產業趨勢反轉風險", MEDIUM_RISK_WEIGHTS.industryReversal, [
      scoreFactor("industry", "產業風險", context?.industryRiskScore, finite(context?.industryRiskScore) ? context.industryRiskScore : finite(context?.industryTrendScore) ? 100 - context.industryTrendScore : null, 2, "market_context"),
    ]),
    scoreComponent("financialEvent", "財務與事件風險", MEDIUM_RISK_WEIGHTS.financialEvent, [
      scoreFactor("debt", "負債風險", financial.debtRatio, interpolate(financial.debtRatio, [[20, 5], [50, 25], [70, 60], [90, 100]]), 2, "financial"),
      scoreFactor("event", "事件風險", context?.eventRiskScore, finite(context?.eventRiskScore) ? context.eventRiskScore : null, 1, "news_context"),
      scoreFactor("restriction", "重大交易限制", risk?.hardExcluded, risk?.hardExcluded == null ? null : risk.hardExcluded ? 100 : 0, 2, "risk_registry"),
    ]),
  ];
}

function tradePlan(model, stock, deep) {
  const price = latestPrice(stock, deep);
  const atr = finite(deep?.price?.atr14) ? Number(deep.price.atr14)
    : finite(deep?.price?.atrPct) && finite(price) ? price * Number(deep.price.atrPct) / 100 : null;
  if (!finite(price) || !finite(atr) || atr <= 0) {
    return {
      idealEntryZone: null, breakoutConfirmationPrice: null, doNotChaseAbove: null,
      stopLoss: null, firstTarget: null, secondTarget: null, riskReward: null,
      suggestedShares: null, status: "insufficient_data",
    };
  }
  const isShort = model === "short";
  const supportPeriod = isShort ? 20 : 60;
  const support = supportFromHistory(deep?.priceHistory, supportPeriod);
  const breakout = priorHighFromHistory(deep?.priceHistory, supportPeriod);
  const entryLow = Math.max(0, price - atr * (isShort ? 0.35 : 0.75));
  const entryHigh = price + atr * (isShort ? 0.15 : 0.3);
  const stopA = finite(support) ? support - atr * (isShort ? 0.3 : 0.5) : null;
  const stopB = price - atr * (isShort ? 1.5 : 2.5);
  const validStops = [stopA, stopB].filter((value) => finite(value) && value > 0 && value < price);
  const stopLoss = validStops.length ? Math.max(...validStops) : null;
  const riskAmount = finite(stopLoss) ? price - stopLoss : null;
  const firstTarget = finite(riskAmount) ? price + riskAmount * (isShort ? 1 : 1.5) : null;
  const secondTarget = finite(riskAmount) ? price + riskAmount * (isShort ? 2 : 3) : null;
  const riskReward = finite(riskAmount) && riskAmount > 0 ? (secondTarget - price) / riskAmount : null;
  return {
    idealEntryZone: { low: round(entryLow), high: round(entryHigh) },
    breakoutConfirmationPrice: round(breakout),
    doNotChaseAbove: round(price + atr * (isShort ? 0.6 : 1.2)),
    support: round(support),
    stopLoss: round(stopLoss),
    stopLossCandidates: { supportAtr: round(stopA), priceAtr: round(stopB) },
    firstTarget: round(firstTarget),
    secondTarget: round(secondTarget),
    riskReward: round(riskReward),
    suggestedShares: null,
    status: finite(stopLoss) ? "ready" : "insufficient_data",
  };
}

function emptyForecast(horizon) {
  return {
    horizonDays: horizon,
    dataState: "insufficient_history",
    upProbability: null,
    expectedNetReturn: null,
    returnRange: { p10: null, p50: null, p90: null },
    averageMfe: null,
    averageMae: null,
    targetFirstProbability: null,
    sampleSize: 0,
    calibrationLevel: null,
  };
}

function scoreDecile(score) {
  return finite(score) ? Math.max(0, Math.min(9, Math.floor(Number(score) / 10))) : null;
}

function selectCalibrationBucket(signal, horizon, buckets) {
  if (!Array.isArray(buckets) || !finite(signal?.score) || !signal?.style) return null;
  const regime = normalizedRegime(signal.regime);
  const decile = scoreDecile(signal.score);
  const exact = buckets
    .filter((row) => row.model === signal.model && Number(row.horizonDays) === Number(horizon) && row.style === signal.style && normalizedRegime(row.regime) === regime && Number(row.scoreDecile) === decile && Number(row.sampleSize) >= 100)
    .sort((a, b) => Number(b.sampleSize) - Number(a.sampleSize))[0];
  if (exact) return { ...exact, calibrationLevel: "style_regime_decile" };
  const fallback = buckets
    .filter((row) => row.model === signal.model && Number(row.horizonDays) === Number(horizon) && [null, undefined, "all"].includes(row.style) && normalizedRegime(row.regime) === regime && Number(row.sampleSize) >= 150)
    .sort((a, b) => Number(b.sampleSize) - Number(a.sampleSize))[0];
  return fallback ? { ...fallback, calibrationLevel: "model_regime" } : null;
}

export function applyCalibration(signal, buckets = []) {
  const horizons = signal?.model === "short" ? SHORT_HORIZONS : MEDIUM_HORIZONS;
  return Object.fromEntries(horizons.map((horizon) => {
    const bucket = selectCalibrationBucket(signal, horizon, buckets);
    if (!bucket) return [String(horizon), emptyForecast(horizon)];
    return [String(horizon), {
      horizonDays: horizon,
      dataState: "calibrated",
      upProbability: round(bucket.upProbability, 1),
      expectedNetReturn: round(bucket.expectedNetReturn),
      returnRange: {
        p10: round(bucket.returnP10),
        p50: round(bucket.returnP50),
        p90: round(bucket.returnP90),
      },
      averageMfe: round(bucket.averageMfe),
      averageMae: round(bucket.averageMae),
      targetFirstProbability: round(bucket.targetFirstProbability, 1),
      sampleSize: Number(bucket.sampleSize),
      calibrationLevel: bucket.calibrationLevel,
    }];
  }));
}

function gate(key, status, reason) {
  return { key, status: status === true ? "pass" : status === false ? "fail" : "unknown", reason };
}

function liquidityGate(stock, deep, risk, model, completeness) {
  if (risk?.hardExcluded === true || risk?.tradingStopped === true || risk?.fullDelivery === true || risk?.severeDisposition === true) {
    return gate("data_liquidity_status", false, "交易狀態或重大風險名單不合格");
  }
  const group = groupOf(stock, deep);
  const minimumValue = group === "otc" ? 10_000_000 : 20_000_000;
  const minimumVolume = group === "otc" ? 100 : group === "etf" ? 500 : 300;
  const rows = Number(deep?.price?.rows || deep?.priceHistory?.length || 0);
  const minimumRows = model === "short" ? 120 : 240;
  if (!finite(stock?.value) || !finite(stock?.volume) || risk?.coverageComplete === false || rows < minimumRows || !finite(completeness)) {
    return gate("data_liquidity_status", null, "價格歷史、成交量、成交金額或交易狀態資料不足");
  }
  return gate("data_liquidity_status", Number(stock.value) >= minimumValue && Number(stock.volume) >= minimumVolume && completeness >= 80, "資料完整度、流動性與交易狀態檢查");
}

function marketGate(model, style, context) {
  const regime = normalizedRegime(context?.regime ?? context?.marketRegime);
  if (!regime) return gate("market_environment", null, "缺少市場環境分類");
  if (regime === "strong_bear") return gate("market_environment", false, "強勢空頭不開放主要推薦");
  if (model === "short" && regime === "bear" && !["oversold_rebound", "event_catalyst"].includes(style)) return gate("market_environment", false, "偏空市場只允許反彈或明確事件策略");
  if (model === "medium" && regime === "bear" && style !== "value_recovery") return gate("market_environment", false, "偏空市場只允許價值回升類型觀察");
  return gate("market_environment", true, "市場環境允許此策略");
}

function trendGate(model, style, deep) {
  const price = deep?.price || {};
  if (!style) return gate("trend_structure", null, "資料不足，無法辨識策略類型");
  let pass = null;
  if (model === "short") {
    if (style === "momentum_breakout") pass = price.breakout20 === true && finite(price.volumeRatio) && price.volumeRatio >= 1.3;
    if (style === "trend_pullback") pass = finite(price.lastClose) && finite(price.ma60) && price.lastClose > price.ma60 && finite(price.distanceMa20) && price.distanceMa20 >= -3;
    if (style === "institutional_flow") pass = finite(price.lastClose) && finite(price.ma20) ? price.lastClose > price.ma20 : null;
    if (style === "event_catalyst") pass = finite(price.lastClose) && finite(price.ma20) ? price.lastClose > price.ma20 || Number(price.return5) > 0 : null;
    if (style === "oversold_rebound") pass = finite(price.rsi14) && finite(price.return5) ? price.rsi14 <= 40 && price.return5 > 0 : null;
  } else {
    pass = finite(price.lastClose) && finite(price.ma60) && finite(price.ma60Slope5)
      ? price.lastClose > price.ma60 && price.ma60Slope5 >= 0
      : null;
  }
  return gate("trend_structure", pass, "策略專屬趨勢與均線結構檢查");
}

function relativeStrengthGate(model, deep, context) {
  const relative = model === "short" ? deep?.price?.relative20 : deep?.price?.relative60;
  const percentile = context?.relativeStrengthPercentile;
  if (!finite(relative) && !finite(percentile)) return gate("relative_strength", null, "缺少相對大盤或產業強度");
  return gate("relative_strength", (finite(relative) && relative >= 0) || (finite(percentile) && percentile >= 55), "個股相對大盤與產業強度檢查");
}

function supportGate(model, deep, context) {
  const institutional = deep?.institutional || {};
  const revenue = deep?.revenue || {};
  const financial = deep?.financial || {};
  const catalyst = context?.newsEventScore ?? context?.catalystScore;
  const candidates = model === "short"
    ? [institutional.inst5, revenue.yoy, catalyst]
    : [institutional.inst20, revenue.avg3Yoy, financial.epsYoy, catalyst];
  if (!candidates.some(finite)) return gate("fundamental_flow_event_support", null, "營收、獲利、法人及事件資料皆不足");
  return gate("fundamental_flow_event_support", candidates.some((value) => finite(value) && value > 0), "至少一項實質支撐為正");
}

function entryGate(model, deep, plan) {
  const distance = model === "short" ? deep?.price?.distanceMa20 : deep?.price?.distanceMa60;
  if (!finite(distance) || !finite(plan?.riskReward)) return gate("reasonable_entry", null, "缺少乖離、ATR、支撐或風報比資料");
  const maximumDistance = model === "short" ? 15 : 25;
  const minimumRiskReward = model === "short" ? 1.5 : 2;
  return gate("reasonable_entry", distance <= maximumDistance && plan.riskReward >= minimumRiskReward, "價格乖離與規則化風報比檢查");
}

function expectancyGate(forecasts) {
  const calibrated = Object.values(forecasts || {}).filter((row) => row.dataState === "calibrated" && finite(row.expectedNetReturn));
  if (!calibrated.length) return gate("positive_expectancy", null, "尚無足夠 Walk-forward 校準樣本");
  return gate("positive_expectancy", calibrated.some((row) => row.expectedNetReturn > 0), "扣除成本與滑價後的交易期望值");
}

function costAdjustedGate(ranking) {
  if (!finite(ranking?.netOpportunityScore)) return gate("cost_adjusted_rank", null, "缺少風險或交易成本資料");
  return gate("cost_adjusted_rank", ranking.netOpportunityScore >= 55, "扣除成本、下跌風險與換手懲罰後的相對排名");
}

function reasonsFromComponents(components, positive = true) {
  return components.flatMap((component) => component.factors
    .filter((factor) => finite(factor.score) && (positive ? factor.score >= 72 : factor.score <= 28))
    .map((factor) => ({ label: factor.label, score: factor.score })))
    .sort((a, b) => positive ? b.score - a.score : a.score - b.score)
    .slice(0, 5)
    .map((row) => row.label);
}

function chooseAction(model, official, score, riskScore, style, gates) {
  if (gates.some((row) => row.status === "unknown") || !finite(score) || !finite(riskScore) || !style) return "資料不足";
  if (riskScore >= 75 || gates.some((row) => row.status === "fail")) return "風險過高";
  if (model === "short") {
    if (!official) return "觀察";
    if (style === "momentum_breakout") return "等待突破";
    if (style === "trend_pullback") return "等待拉回";
    return "可以布局";
  }
  if (!official) return score >= 60 ? "等待趨勢確認" : "資料不足";
  if (["growth_momentum", "industry_trend", "institutional_accumulation"].includes(style)) return "等待回檔";
  if (style === "value_recovery") return "價格合理";
  return "適合布局";
}

function failureConditions(model, style) {
  if (model === "short") {
    return [
      "跌破規則化停損價",
      style === "momentum_breakout" ? "突破後兩個交易日內跌回原平台" : "三個交易日內未達正 0.5R",
      "五個交易日內量價與法人方向沒有延續",
      style === "event_catalyst" ? "事件題材失去市場反應" : "原先成立的短期策略條件消失",
    ];
  }
  return [
    "月營收或 EPS 成長明顯減速",
    "毛利率持續下降",
    "法人累計買超轉為大量賣超",
    "跌破中期重要支撐或六十日均線",
    "產業需求、產品報價或政策反轉",
    "股價大幅超過類型調整後的合理估值區間",
  ];
}

function mediumGrowthState(deep) {
  const growth = deep?.revenue?.avg3Yoy ?? deep?.revenue?.yoy;
  const acceleration = deep?.revenue?.acceleration3;
  if (!finite(growth) || !finite(acceleration)) return null;
  if (growth <= 0) return "declining";
  if (acceleration >= 2) return "accelerating";
  if (acceleration <= -2) return "slowing";
  return "stable";
}

function signalMetrics(model, components, deep, context) {
  const componentScore = (key) => components.find((row) => row.key === key)?.score ?? null;
  if (model === "short") {
    return {
      priceVolumeTrend: componentScore("priceVolumeTrend"),
      institutionalStrength: componentScore("institutional"),
      relativeStrengthPercentile: finite(context?.relativeStrengthPercentile) ? round(context.relativeStrengthPercentile, 1) : null,
      catalystStrength: componentScore("revenueEventCatalyst"),
    };
  }
  const valuationScore = componentScore("valuationReasonableness");
  return {
    growthState: mediumGrowthState(deep),
    growthMomentum: componentScore("revenueProfitGrowth"),
    growthAcceleration: finite(deep?.revenue?.acceleration3) ? round(deep.revenue.acceleration3) : null,
    industryTrend: componentScore("industryEnvironment"),
    institutionalStrength: componentScore("institutionalPositioning"),
    relativeStrengthPercentile: finite(context?.relativeStrengthPercentile) ? round(context.relativeStrengthPercentile, 1) : null,
    valuationScore,
    valuationState: !finite(valuationScore) ? null : valuationScore >= 70 ? "reasonable" : valuationScore <= 35 ? "expensive" : "neutral",
  };
}

function buildSignal(model, input) {
  const { stock = {}, deep = {}, risk = {}, context = {}, calibrationBuckets = [] } = input || {};
  const isShort = model === "short";
  const horizons = isShort ? SHORT_HORIZONS : MEDIUM_HORIZONS;
  const components = isShort ? shortComponents(stock, deep, context) : mediumComponents(stock, deep, context);
  const aggregateScore = aggregate(components, 60);
  const riskComponents = isShort ? shortRiskComponents(stock, deep, risk, context) : mediumRiskComponents(stock, deep, risk, context);
  const aggregateRisk = weightedRisk(riskComponents);
  const style = isShort ? shortStyle(deep, context) : mediumStyle(deep, context);
  const plan = tradePlan(model, stock, deep);
  const group = groupOf(stock, deep);
  const costs = estimateExecutionCosts({
    group,
    averageDailyValue: stock?.value ?? deep?.price?.averageValue20,
    atrPct: deep?.price?.atrPct,
    price: latestPrice(stock, deep),
    expectedOrderValue: context?.expectedOrderValue,
    commissionRatePerSidePct: context?.costAssumptions?.commissionRatePerSidePct,
  });
  const researchHorizons = isShort ? [] : MEDIUM_RESEARCH_HORIZONS;
  const rankingByHorizon = Object.fromEntries([...horizons, ...researchHorizons].map((horizon) => [String(horizon), adjustOpportunityScore({
    rawScore: aggregateScore.score,
    riskScore: aggregateRisk.riskScore,
    estimatedTotalCostPct: costs.totalPct,
    model,
    horizonDays: horizon,
    atrPct: deep?.price?.atrPct,
    expectedTurnoverRate: context?.expectedTurnoverRate,
  })]));
  const primaryHorizon = isShort ? 5 : 20;
  const primaryRanking = rankingByHorizon[String(primaryHorizon)];
  const preliminary = {
    version: V20_MODEL_VERSION,
    model,
    symbol: String(stock.symbol || ""),
    name: stock.name || "",
    group,
    asOf: input?.asOf || deep?.price?.lastDate || deep?.priceHistory?.at(-1)?.date || null,
    horizons,
    regime: normalizedRegime(context?.regime ?? context?.marketRegime),
    style,
    score: primaryRanking?.netOpportunityScore ?? null,
    rawOpportunityScore: aggregateScore.score,
    netOpportunityScore: primaryRanking?.netOpportunityScore ?? null,
  };
  const forecasts = applyCalibration(preliminary, calibrationBuckets);
  const gates = [
    liquidityGate(stock, deep, risk, model, aggregateScore.dataCompleteness),
    marketGate(model, style, context),
    trendGate(model, style, deep),
    relativeStrengthGate(model, deep, context),
    supportGate(model, deep, context),
    entryGate(model, deep, plan),
    costAdjustedGate(primaryRanking),
    expectancyGate(forecasts),
  ];
  const scoreThreshold = isShort ? ({ momentum_breakout: 70, trend_pullback: 68, institutional_flow: 67, event_catalyst: 70, oversold_rebound: 72 }[style] ?? 70) : 68;
  const riskThreshold = isShort ? 65 : 60;
  const requiredGates = gates.filter((row) => row.key !== "positive_expectancy" || row.status !== "unknown");
  const official = requiredGates.every((row) => row.status === "pass") && finite(primaryRanking?.netOpportunityScore) && primaryRanking.netOpportunityScore >= scoreThreshold && finite(aggregateRisk.riskScore) && aggregateRisk.riskScore <= riskThreshold;
  const missing = components.flatMap((component) => component.factors.filter((factor) => !finite(factor.score)).map((factor) => factor.label));
  const calibratedForecasts = Object.values(forecasts).filter((row) => row.dataState === "calibrated" && finite(row.expectedNetReturn));
  const optimalHoldingDays = calibratedForecasts.length
    ? calibratedForecasts.sort((a, b) => b.expectedNetReturn - a.expectedNetReturn)[0].horizonDays
    : null;
  return {
    ...preliminary,
    riskScore: aggregateRisk.riskScore,
    confidence: round(Math.min(aggregateScore.dataCompleteness, aggregateRisk.riskCompleteness), 1),
    dataCompleteness: aggregateScore.dataCompleteness,
    riskCompleteness: aggregateRisk.riskCompleteness,
    official,
    recommended: official,
    action: chooseAction(model, official, primaryRanking?.netOpportunityScore, aggregateRisk.riskScore, style, requiredGates),
    opportunityScore: primaryRanking?.netOpportunityScore ?? null,
    costs,
    rankingByHorizon,
    researchHorizons,
    strategy: isShort ? style : null,
    stockType: isShort ? null : style,
    optimalHoldingDays,
    metrics: signalMetrics(model, components, deep, context),
    components,
    riskComponents,
    gates,
    reasons: reasonsFromComponents(components, true),
    risks: reasonsFromComponents(riskComponents, true),
    failureConditions: failureConditions(model, style),
    tradePlan: plan,
    forecasts,
    missing: [...new Set([...(deep?.missing || []), ...missing])].slice(0, 30),
  };
}

export function scoreShortTerm(input) {
  return buildSignal("short", input);
}

export function scoreMediumTerm(input) {
  return buildSignal("medium", input);
}

export function scoreV20Models(input) {
  return {
    version: V20_MODEL_VERSION,
    symbol: String(input?.stock?.symbol || ""),
    short: scoreShortTerm(input),
    medium: scoreMediumTerm(input),
  };
}

export function calculatePositionSize({ capital, riskRatio = 0.005, entryPrice, stopLoss }) {
  if (![capital, riskRatio, entryPrice, stopLoss].every(finite) || Number(capital) <= 0 || Number(riskRatio) <= 0 || Number(riskRatio) > 0.01 || Number(entryPrice) <= Number(stopLoss)) {
    return { status: "invalid_input", maximumRiskAmount: null, shares: null, lots: null };
  }
  const maximumRiskAmount = Number(capital) * Number(riskRatio);
  const shares = Math.floor(maximumRiskAmount / (Number(entryPrice) - Number(stopLoss)));
  return {
    status: "ready",
    maximumRiskAmount: round(maximumRiskAmount),
    shares,
    lots: round(shares / 1000, 3),
  };
}

export const v20ModelInternals = {
  interpolate,
  aggregate,
  normalizedRegime,
  shortStyle,
  mediumStyle,
  tradePlan,
  selectCalibrationBucket,
  scoreDecile,
};
