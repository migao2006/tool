import { deepDataInternals } from "./deep-data.js";

const finite = (value) => value != null && Number.isFinite(Number(value));
const clamp = (value, low = 0, high = 100) => Math.max(low, Math.min(high, value));
const round = (value, digits = 2) => finite(value) ? Number(Number(value).toFixed(digits)) : null;
const mean = (values) => {
  const usable = values.filter(finite).map(Number);
  return usable.length ? usable.reduce((sum, value) => sum + value, 0) / usable.length : null;
};
const sum = (values) => values.filter(finite).reduce((total, value) => total + Number(value), 0);

function interpolate(value, points) {
  if (!finite(value)) return null;
  const sorted = [...points].sort((a, b) => a[0] - b[0]);
  if (value <= sorted[0][0]) return sorted[0][1];
  if (value >= sorted.at(-1)[0]) return sorted.at(-1)[1];
  for (let index = 1; index < sorted.length; index += 1) {
    const [rightX, rightY] = sorted[index];
    const [leftX, leftY] = sorted[index - 1];
    if (value <= rightX) {
      const ratio = (value - leftX) / (rightX - leftX);
      return clamp(leftY + ratio * (rightY - leftY));
    }
  }
  return null;
}

const booleanScore = (value, falseScore = 38) => value == null ? null : value ? 100 : falseScore;
const growthScore = (value) => interpolate(value, [[-30, 0], [-10, 15], [0, 38], [10, 58], [20, 76], [35, 92], [55, 100]]);
const accelerationScore = (value) => interpolate(value, [[-20, 0], [-8, 18], [-2, 38], [0, 50], [5, 72], [12, 92], [20, 100]]);
const flowScore = (value) => {
  if (!finite(value)) return null;
  if (value === 0) return 45;
  const magnitude = Math.log10(Math.abs(value) + 10);
  return clamp(50 + Math.sign(value) * magnitude * 12);
};
const sweetRsiScore = (value) => {
  if (!finite(value)) return null;
  if (value < 30) return interpolate(value, [[0, 5], [30, 38]]);
  if (value <= 50) return interpolate(value, [[30, 38], [50, 72]]);
  if (value <= 67) return interpolate(value, [[50, 72], [60, 94], [67, 88]]);
  if (value <= 80) return interpolate(value, [[67, 88], [75, 55], [80, 20]]);
  return 0;
};
const distanceScore = (value) => {
  if (!finite(value)) return null;
  const distance = Math.abs(value);
  if (value < -10) return 20;
  return interpolate(distance, [[0, 88], [3, 100], [8, 80], [14, 45], [20, 10], [30, 0]]);
};
const inverseChangeScore = (value) => interpolate(value, [[-30, 100], [-10, 82], [0, 58], [10, 35], [30, 8], [60, 0]]);
const cashConversionScore = (value, group) => group === "otc"
  ? interpolate(value, [[-1.5, 10], [-0.5, 25], [0, 42], [0.5, 65], [1, 88], [1.5, 100]])
  : interpolate(value, [[-1, 0], [-0.3, 18], [0, 35], [0.5, 60], [1, 86], [1.5, 100]]);

function item(key, label, weight, value, score, source) {
  return { key, label, weight, value: finite(value) || typeof value === "boolean" ? value : null, score: finite(score) ? clamp(score) : null, source };
}

function category(key, label, weight, items) {
  const expected = sum(items.map((entry) => entry.weight));
  const available = sum(items.filter((entry) => finite(entry.score)).map((entry) => entry.weight));
  const score = available
    ? sum(items.filter((entry) => finite(entry.score)).map((entry) => entry.score * entry.weight)) / available
    : null;
  return {
    key,
    label,
    weight,
    score: round(score, 1),
    coverage: expected ? round((available / expected) * 100, 1) : 0,
    items,
  };
}

function companyCategories(stock, deep, context, group) {
  const revenue = deep?.revenue || {};
  const financial = deep?.financial || {};
  const chip = deep?.institutional || {};
  const margin = deep?.margin || {};
  const price = deep?.price || {};
  const holdings = deep?.holdings || {};
  const trustWeight = group === "otc" ? 17 : 9;
  const foreignWeight = group === "listed" ? 19 : 8;
  const concentrationWeight = group === "otc" ? 15 : 8;
  return [
    category("growth", "營收與獲利成長", 30, [
      item("revenue_yoy", "單月營收年增", 15, revenue.yoy, growthScore(revenue.yoy), "36 月營收"),
      item("revenue_avg3", "近 3 月平均年增", 13, revenue.avg3Yoy, growthScore(revenue.avg3Yoy), "36 月營收"),
      item("revenue_ytd", "累計營收年增", 8, revenue.ytdYoy, growthScore(revenue.ytdYoy), "36 月營收"),
      item("revenue_acceleration", "營收成長加速度", group === "otc" ? 15 : 12, revenue.acceleration3, accelerationScore(revenue.acceleration3), "36 月營收"),
      item("revenue_streak", "年增率連續上升", 8, revenue.consecutiveAcceleration, interpolate(revenue.consecutiveAcceleration, [[0, 35], [1, 58], [2, 78], [3, 93], [5, 100]]), "36 月營收"),
      item("revenue_high", "近 12 月營收新高", 6, revenue.new12MonthHigh, booleanScore(revenue.new12MonthHigh), "36 月營收"),
      item("same_month_record", "歷年同期新高", 5, revenue.sameMonthRecord, booleanScore(revenue.sameMonthRecord), "36 月營收"),
      item("eps_yoy", "EPS 年增", 10, financial.epsYoy, growthScore(financial.epsYoy), "12 季財報"),
      item("margin_trend", "營業利益率年變化", 7, financial.operatingMarginYoyChange, interpolate(financial.operatingMarginYoyChange, [[-8, 0], [-3, 25], [0, 55], [2, 78], [5, 100]]), "12 季財報"),
      item("cash_conversion", "近四季盈餘現金轉換", group === "otc" ? 5 : 7, financial.cashConversion, cashConversionScore(financial.cashConversion, group), "現金流量表（TTM）"),
      ...(revenue.postReleaseStatus === "pending-five-trading-days" ? [] : [
        item("post_release", "營收公布後 5 日反應", 4, revenue.postRelease5, interpolate(revenue.postRelease5, [[-10, 0], [-3, 25], [0, 50], [3, 72], [8, 100]]), "營收公布日＋價量"),
      ]),
    ]),
    category("chip", "法人與籌碼", 25, [
      item("foreign20", "外資 20 日累計", foreignWeight, chip.foreign20, flowScore(chip.foreign20), "法人歷史"),
      item("foreign_streak", "外資連買天數", group === "listed" ? 11 : 5, chip.foreignStreak, interpolate(chip.foreignStreak, [[0, 38], [1, 55], [3, 75], [5, 90], [8, 100]]), "法人歷史"),
      item("trust20", "投信 20 日累計", trustWeight, chip.trust20, flowScore(chip.trust20), "法人歷史"),
      item("trust_streak", "投信連買天數", group === "otc" ? 10 : 5, chip.trustStreak, interpolate(chip.trustStreak, [[0, 40], [1, 58], [3, 80], [5, 95], [8, 100]]), "法人歷史"),
      item("inst_intensity", "法人買超占量", 18, chip.intensity5, interpolate(chip.intensity5, [[-8, 0], [-2, 25], [0, 50], [1, 65], [3, 82], [7, 100]]), "法人歷史＋價量"),
      item("margin20", "融資 20 日增減", 11, margin.marginChange20, inverseChangeScore(margin.marginChange20), "融資融券歷史"),
      ...(margin.financingEligible === false ? [] : [
        item("margin_usage", "融資使用率", 7, margin.marginUsage, interpolate(margin.marginUsage, [[0, 92], [10, 85], [25, 62], [40, 35], [60, 0]]), "融資融券歷史"),
      ]),
      item("large_holders", "400 張以上持股", concentrationWeight, holdings.large400Ratio, interpolate(holdings.large400Ratio, [[20, 20], [40, 48], [60, 72], [75, 88], [90, 100]]), "TDCC 週資料"),
      item("retail_holders", "10 張以下持股", group === "otc" ? 8 : 5, holdings.retail10Ratio, interpolate(holdings.retail10Ratio, [[0, 100], [10, 82], [25, 55], [45, 25], [70, 0]]), "TDCC 週資料"),
    ]),
    category("technical", "技術與價量", 25, [
      item("above_ma20", "站上 20 日線", 10, finite(price.lastClose) && finite(price.ma20) ? price.lastClose > price.ma20 : null, finite(price.lastClose) && finite(price.ma20) ? booleanScore(price.lastClose > price.ma20, 15) : null, "250 日價量"),
      item("above_ma60", "站上 60 日線", 10, finite(price.lastClose) && finite(price.ma60) ? price.lastClose > price.ma60 : null, finite(price.lastClose) && finite(price.ma60) ? booleanScore(price.lastClose > price.ma60, 18) : null, "250 日價量"),
      item("ma20_slope", "20 日線斜率", 11, price.ma20Slope5, interpolate(price.ma20Slope5, [[-5, 0], [-1, 25], [0, 50], [1, 72], [3, 94], [6, 100]]), "250 日價量"),
      item("ma_alignment", "20／60／120 均線排列", 10, finite(price.ma20) && finite(price.ma60) && finite(price.ma120) ? price.ma20 > price.ma60 && price.ma60 > price.ma120 : null, finite(price.ma20) && finite(price.ma60) && finite(price.ma120) ? booleanScore(price.ma20 > price.ma60 && price.ma60 > price.ma120, 28) : null, "250 日價量"),
      item("relative20", "20 日相對大盤強弱", 13, price.relative20, interpolate(price.relative20, [[-15, 0], [-5, 25], [0, 52], [5, 75], [12, 95], [20, 100]]), "個股＋市場指數"),
      item("breakout", "20 日突破", 9, price.breakout20, booleanScore(price.breakout20, 42), "250 日價量"),
      item("volume", "5／20 日量能比", 9, price.volumeRatio, interpolate(price.volumeRatio, [[0.4, 20], [0.8, 50], [1, 62], [1.5, 90], [2, 100], [3.5, 75]]), "250 日價量"),
      item("volume_structure", "漲／跌日量能結構", 7, price.upDownVolumeRatio, interpolate(price.upDownVolumeRatio, [[0.4, 0], [0.8, 38], [1, 58], [1.4, 82], [2, 100]]), "250 日價量"),
      item("rsi", "RSI 位置", 7, price.rsi14, sweetRsiScore(price.rsi14), "250 日價量"),
      item("distance", "距 20 日線", 8, price.distanceMa20, distanceScore(price.distanceMa20), "250 日價量"),
      item("macd", "MACD 柱狀體", 6, price.macdHistogram, finite(price.macdHistogram) ? (price.macdHistogram > 0 ? 82 : 28) : null, "250 日價量"),
    ]),
    category("valuation", "估值合理性", 10, [
      item("pe_percentile", "同組／同業本益比百分位", 35, context?.peValuePercentile, finite(context?.peValuePercentile) ? context.peValuePercentile : null, "當日同業比較"),
      item("pb_percentile", "同組／同業淨值比百分位", 20, context?.pbValuePercentile, finite(context?.pbValuePercentile) ? context.pbValuePercentile : null, "當日同業比較"),
      item("growth_adjusted_pe", "成長調整本益比", 30, finite(stock.pe) && finite(revenue.avg3Yoy) && revenue.avg3Yoy > 0 ? stock.pe / revenue.avg3Yoy : null, finite(stock.pe) && finite(revenue.avg3Yoy) && revenue.avg3Yoy > 0 ? interpolate(stock.pe / revenue.avg3Yoy, [[0.2, 100], [0.8, 85], [1.2, 65], [2, 35], [3, 10], [5, 0]]) : null, "估值＋營收歷史"),
      item("yield", "殖利率", 15, stock.yield, interpolate(stock.yield, [[0, 25], [2, 45], [4, 72], [6, 90], [9, 100]]), "當日估值"),
    ]),
    category("market", "大盤與產業環境", 10, [
      item("market_trend", "大盤／櫃買 20 日趨勢", 35, price.marketReturn20, interpolate(price.marketReturn20, [[-15, 0], [-5, 25], [0, 52], [5, 75], [12, 100]]), "市場指數"),
      item("market_breadth", "市場上漲家數比", 25, context?.marketBreadth, interpolate(context?.marketBreadth, [[25, 0], [40, 35], [50, 55], [60, 78], [75, 100]]), "當日市場廣度"),
      item("industry_breadth", "產業上漲家數比", 25, context?.industryBreadth, interpolate(context?.industryBreadth, [[20, 0], [40, 35], [50, 55], [65, 82], [80, 100]]), "當日產業廣度"),
      item("industry_change", "產業相對大盤", 15, context?.industryRelativeChange, interpolate(context?.industryRelativeChange, [[-5, 0], [-2, 25], [0, 52], [2, 78], [5, 100]]), "當日產業比較"),
    ]),
  ];
}

function etfCategories(stock, deep, context) {
  const price = deep?.price || {};
  const profile = deep?.etf || {};
  const estimatedAum = finite(profile.units) && finite(stock.close) ? profile.units * stock.close : null;
  return [
    category("trend", "追蹤趨勢與動能", 35, [
      item("above_ma20", "站上 20 日線", 15, finite(price.lastClose) && finite(price.ma20) ? price.lastClose > price.ma20 : null, finite(price.lastClose) && finite(price.ma20) ? booleanScore(price.lastClose > price.ma20, 15) : null, "250 日價量"),
      item("above_ma60", "站上 60 日線", 15, finite(price.lastClose) && finite(price.ma60) ? price.lastClose > price.ma60 : null, finite(price.lastClose) && finite(price.ma60) ? booleanScore(price.lastClose > price.ma60, 20) : null, "250 日價量"),
      item("ma20_slope", "20 日線斜率", 15, price.ma20Slope5, interpolate(price.ma20Slope5, [[-5, 0], [-1, 25], [0, 50], [1, 75], [3, 100]]), "250 日價量"),
      item("relative20", "相對市場 20 日強弱", 18, price.relative20, interpolate(price.relative20, [[-12, 0], [-4, 25], [0, 52], [4, 75], [10, 100]]), "ETF＋市場指數"),
      item("volume", "量能趨勢", 12, price.volumeRatio, interpolate(price.volumeRatio, [[0.5, 20], [0.9, 52], [1.3, 82], [2, 100], [3.5, 72]]), "250 日價量"),
      item("rsi", "RSI 位置", 10, price.rsi14, sweetRsiScore(price.rsi14), "250 日價量"),
      item("distance", "距 20 日線", 15, price.distanceMa20, distanceScore(price.distanceMa20), "250 日價量"),
    ]),
    category("liquidity", "流動性與規模", 25, [
      item("volume", "成交量", 35, stock.volume, interpolate(stock.volume, [[100, 0], [500, 35], [2_000, 62], [10_000, 86], [50_000, 100]]), "當日行情"),
      item("value", "成交金額", 40, stock.value, interpolate(stock.value, [[5_000_000, 0], [20_000_000, 35], [100_000_000, 65], [500_000_000, 88], [2_000_000_000, 100]]), "當日行情"),
      item("aum", "推估規模", 25, estimatedAum, interpolate(estimatedAum, [[100_000_000, 10], [1_000_000_000, 40], [10_000_000_000, 70], [100_000_000_000, 95], [500_000_000_000, 100]]), "發行單位數×市價"),
    ]),
    category("structure", "基金結構與風險", 20, [
      item("profile", "基金基本資料", 20, Boolean(deep?.etf), booleanScore(Boolean(deep?.etf), 0), "MOPS 基金資料"),
      item("leverage", "非槓桿型", 25, profile.leveraged, profile.leveraged == null ? null : profile.leveraged ? 0 : 100, "MOPS 基金資料"),
      item("inverse", "非反向型", 25, profile.inverse, profile.inverse == null ? null : profile.inverse ? 0 : 100, "MOPS 基金資料"),
      item("foreign", "國家／匯率風險", 15, profile.foreignExposure, profile.foreignExposure == null ? null : profile.foreignExposure ? 48 : 82, "MOPS 基金資料"),
      item("atr", "波動度", 15, price.atrPct, interpolate(price.atrPct, [[0.5, 100], [2, 85], [4, 58], [7, 25], [12, 0]]), "250 日價量"),
    ]),
    category("tracking", "淨值與追蹤品質", 10, [
      item("premium", "淨值折溢價", 30, deep?.etf?.premiumDiscount, finite(deep?.etf?.premiumDiscount) ? interpolate(Math.abs(deep.etf.premiumDiscount), [[0, 100], [0.5, 80], [1, 50], [2, 10], [4, 0]]) : null, "基金淨值"),
      item("tracking_error", "追蹤誤差", 30, deep?.etf?.trackingError, finite(deep?.etf?.trackingError) ? interpolate(deep.etf.trackingError, [[0, 100], [0.5, 85], [1, 60], [2, 20], [4, 0]]) : null, "基金公開資訊"),
      item("fees", "經理費與內扣費用", 20, deep?.etf?.fees, finite(deep?.etf?.fees) ? interpolate(deep.etf.fees, [[0.1, 100], [0.5, 75], [1, 45], [2, 10]]) : null, "基金公開資訊"),
      item("concentration", "成分股集中度", 20, deep?.etf?.top10Concentration, finite(deep?.etf?.top10Concentration) ? interpolate(deep.etf.top10Concentration, [[20, 95], [40, 80], [60, 55], [80, 20], [95, 0]]) : null, "基金持股"),
    ]),
    category("market", "市場環境", 10, [
      item("market_trend", "市場 20 日趨勢", 60, price.marketReturn20, interpolate(price.marketReturn20, [[-15, 0], [-5, 25], [0, 52], [5, 78], [12, 100]]), "市場指數"),
      item("market_breadth", "市場上漲家數比", 40, context?.marketBreadth, interpolate(context?.marketBreadth, [[25, 0], [40, 35], [50, 55], [65, 85], [80, 100]]), "當日市場廣度"),
    ]),
  ];
}

function riskAssessment(stock, deep, currentRisk, group) {
  const flags = [];
  const hard = [];
  let deduction = 0;
  const price = deep?.price || {};
  const revenue = deep?.revenue || {};
  const financial = deep?.financial || {};
  const floor = group === "otc" ? { volume: 100, value: 10_000_000 } : group === "etf" ? { volume: 500, value: 20_000_000 } : { volume: 300, value: 20_000_000 };
  if (currentRisk?.hardExcluded) hard.push(...(currentRisk.flags || ["官方交易風險名單"]));
  if (!finite(stock.volume) || stock.volume < floor.volume || !finite(stock.value) || stock.value < floor.value) {
    hard.push("流動性低於本組最低門檻");
  }
  if (price.jumpAnomaly) hard.push("價格可能未完成還原，停用技術評分");
  if (price.limitUpStreak >= 2) {
    deduction += 12;
    flags.push(`連續 ${price.limitUpStreak} 日接近漲停`);
  }
  if (currentRisk?.attention) {
    deduction += 5;
    flags.push("官方注意股票");
  }
  if (finite(price.distanceMa20) && price.distanceMa20 > 18) {
    deduction += 7;
    flags.push(`距 20 日線 ${round(price.distanceMa20, 1)}%，短線過熱`);
  }
  if (finite(price.rsi14) && price.rsi14 >= 80) {
    deduction += 5;
    flags.push(`RSI ${round(price.rsi14, 1)} 過熱`);
  }
  const atrLimit = group === "otc" ? 8 : group === "etf" ? 6 : 6;
  if (finite(price.atrPct) && price.atrPct > atrLimit) {
    deduction += group === "otc" ? 6 : 4;
    flags.push(`ATR 波動 ${round(price.atrPct, 1)}%`);
  }
  if (group !== "etf") {
    if (finite(revenue.yoy) && revenue.yoy > 10 && finite(financial.operatingMarginYoyChange) && financial.operatingMarginYoyChange < -3) {
      deduction += 5;
      flags.push("營收成長但營業利益率明顯下降");
    }
    const cashFlow = financial.ttmOperatingCashFlow ?? financial.operatingCashFlow;
    if (finite(financial.epsYoy) && financial.epsYoy > 0 && finite(cashFlow) && cashFlow < 0) {
      const severe = finite(financial.cashConversion) && financial.cashConversion <= -1;
      deduction += group === "otc" ? (severe ? 4 : 2) : (severe ? 6 : 4);
      flags.push("獲利成長但近四季營業現金流為負");
    }
    if (finite(financial.inventoryYoy) && finite(financial.revenueYoy) && financial.inventoryYoy > financial.revenueYoy + 20) {
      deduction += 4;
      flags.push("存貨增速顯著高於營收");
    }
    if (finite(financial.receivablesYoy) && finite(financial.revenueYoy) && financial.receivablesYoy > financial.revenueYoy + 20) {
      deduction += 4;
      flags.push("應收帳款增速顯著高於營收");
    }
    if (finite(financial.debtRatio) && financial.debtRatio > 80) {
      deduction += 4;
      flags.push("負債比偏高");
    }
  } else if (deep?.etf?.leveraged || deep?.etf?.inverse) {
    deduction += 10;
    flags.push(deep.etf.leveraged ? "槓桿 ETF" : "反向 ETF");
  }
  return {
    hardExcluded: hard.length > 0,
    hardReasons: [...new Set(hard)],
    deduction: Math.min(30, deduction),
    flags: [...new Set(flags)],
  };
}

function scoreTier(score) {
  if (score >= 80) return "強勢機會候選";
  if (score >= 70) return "值得加入觀察";
  if (score >= 60) return "條件普通，等待改善";
  return "暫不列入";
}

function archetypes(stock, deep, categories) {
  const revenue = deep?.revenue || {};
  const financial = deep?.financial || {};
  const chip = deep?.institutional || {};
  const price = deep?.price || {};
  const matches = [];
  if (finite(revenue.acceleration3) && revenue.acceleration3 > 2 && finite(financial.operatingMarginYoyChange) && financial.operatingMarginYoyChange >= -1 && (chip.inst5 || 0) > 0 && (price.breakout20 || (price.distanceHigh20 || -100) > -3)) {
    matches.push("營運加速型");
  }
  if ((chip.foreignStreak >= 3 || chip.trustStreak >= 3 || (chip.intensity5 || 0) >= 2) && (deep?.margin?.marginChange5 || 0) <= 0 && (price.distanceMa20 || 0) < 15) {
    matches.push("籌碼轉強型");
  }
  if ((price.relative20 || 0) < 0 && (revenue.avg3Yoy || 0) >= 0 && (price.volumeRatio || 0) >= 1.1 && (categories.find((entry) => entry.key === "valuation")?.score || 0) >= 60) {
    matches.push("落後補漲型");
  }
  if (deep?.instrumentType === "ETF" && (price.ma20Slope5 || 0) > 0 && (price.distanceMa20 || 0) < 10) matches.push("趨勢型 ETF");
  return matches.length ? matches : ["綜合觀察型"];
}

export function scoreOpportunity({ stock, deep, risk = {}, context = {} }) {
  const group = deep?.instrumentType === "ETF" || stock.instrumentType === "ETF"
    ? "etf"
    : stock.market === "上櫃" ? "otc" : "listed";
  const categories = group === "etf"
    ? etfCategories(stock, deep, context)
    : companyCategories(stock, deep, context, group);
  if (deep?.price?.jumpAnomaly) {
    const technical = categories.find((entry) => ["technical", "trend"].includes(entry.key));
    if (technical) {
      technical.score = null;
      technical.coverage = 0;
    }
  }
  const availableCategories = categories.filter((entry) => finite(entry.score));
  const availableWeight = sum(availableCategories.map((entry) => entry.weight));
  const baseScore = availableWeight
    ? sum(availableCategories.map((entry) => entry.score * entry.weight)) / availableWeight
    : 0;
  const riskResult = riskAssessment(stock, deep, risk, group);
  const finalScore = clamp(Math.round(baseScore - riskResult.deduction));
  const totalExpected = sum(categories.map((entry) => entry.weight));
  const covered = sum(categories.map((entry) => entry.weight * entry.coverage / 100));
  const riskCoverage = risk?.coverageComplete === false ? 0.7 : 1;
  const factorCoverage = totalExpected ? covered / totalExpected : 0;
  const historyCoverage = group === "etf"
    ? (
        Math.min(1, Number(deep?.price?.rows || 0) / 120) * 0.85 +
        (deep?.etf ? 1 : 0) * 0.15
      )
    : (
        Math.min(1, Number(deep?.revenue?.continuousMonths || 0) / 24) * 0.30 +
        Math.min(1, Number(deep?.financial?.continuousQuarters || 0) / 8) * 0.10 +
        (Number(deep?.financial?.sourceCoverage?.balanceRows || 0) > 0 ? 0.05 : 0) +
        (Number(deep?.financial?.sourceCoverage?.cashflowRows || 0) > 0 ? 0.05 : 0) +
        Math.min(1, Number(deep?.price?.rows || 0) / 120) * 0.25 +
        Math.min(1, Number(deep?.institutional?.days || 0) / 20) * 0.15 +
        Math.min(1, Number(deep?.margin?.days || 0) / 20) * 0.10
      );
  const confidence = clamp(Math.round(factorCoverage * historyCoverage * 100 * riskCoverage));
  const missing = categories.flatMap((entry) => entry.items.filter((factor) => !finite(factor.score)).map((factor) => factor.label));
  const staleEssentialSource = group !== "etf" && ["revenue", "income", "balance", "cashflow"]
    .some((key) => deep?.sourceDiagnostics?.[key]?.status === "stale-source-period");
  const official = confidence >= 70 &&
    deep?.price?.sufficient === true &&
    risk?.coverageComplete !== false &&
    !staleEssentialSource &&
    !riskResult.hardExcluded &&
    finalScore >= 60;
  const reasons = categories
    .flatMap((entry) => entry.items.filter((factor) => finite(factor.score) && factor.score >= 75).map((factor) => ({ label: factor.label, score: factor.score })))
    .sort((a, b) => b.score - a.score)
    .slice(0, 5)
    .map((entry) => entry.label);
  return {
    symbol: stock.symbol,
    name: stock.name,
    group,
    score: finalScore,
    baseScore: round(baseScore, 1),
    confidence,
    historyCoverage: round(historyCoverage * 100, 1),
    official,
    freshnessVerified: !staleEssentialSource,
    tier: scoreTier(finalScore),
    categories,
    risk: riskResult,
    archetypes: archetypes(stock, deep, categories),
    reasons,
    missing: [...new Set([...(deep?.missing || []), ...missing])].slice(0, 20),
  };
}

export function buildPeerContexts(stocks, marketBreadth = null) {
  const bySymbol = {};
  const groups = new Map();
  stocks.forEach((stock) => {
    const group = stock.instrumentType === "ETF" ? "etf" : stock.market === "上櫃" ? "otc" : "listed";
    const key = `${group}:${stock.industry || "未分類"}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(stock);
  });
  const percentile = (values, value, lowerBetter = false) => {
    const usable = values.filter(finite).map(Number).sort((a, b) => a - b);
    if (!usable.length || !finite(value)) return null;
    const count = usable.filter((entry) => lowerBetter ? entry >= value : entry <= value).length;
    return round((count / usable.length) * 100, 1);
  };
  stocks.forEach((stock) => {
    const group = stock.instrumentType === "ETF" ? "etf" : stock.market === "上櫃" ? "otc" : "listed";
    let peers = groups.get(`${group}:${stock.industry || "未分類"}`) || [];
    if (peers.length < 5) peers = stocks.filter((row) => (row.instrumentType === "ETF" ? "etf" : row.market === "上櫃" ? "otc" : "listed") === group);
    const validChanges = peers.map((row) => row.change).filter(finite);
    const marketChanges = stocks.filter((row) => (row.instrumentType === "ETF" ? "etf" : row.market === "上櫃" ? "otc" : "listed") === group).map((row) => row.change).filter(finite);
    const industryMean = mean(validChanges);
    const marketMean = mean(marketChanges);
    bySymbol[stock.symbol] = {
      peValuePercentile: percentile(peers.map((row) => row.pe).filter((value) => value > 0), stock.pe, true),
      pbValuePercentile: percentile(peers.map((row) => row.pb).filter((value) => value > 0), stock.pb, true),
      industryBreadth: validChanges.length ? validChanges.filter((value) => value > 0).length / validChanges.length * 100 : null,
      industryRelativeChange: finite(industryMean) && finite(marketMean) ? industryMean - marketMean : null,
      marketBreadth: finite(marketBreadth)
        ? marketBreadth
        : marketChanges.length ? marketChanges.filter((value) => value > 0).length / marketChanges.length * 100 : null,
    };
  });
  return bySymbol;
}

function revenueAsOf(history, asOf) {
  const rows = history.filter((row) => row.availableAt && row.availableAt <= asOf);
  if (!rows.length) return { months: 0 };
  const latest = rows.at(-1);
  const currentYear = rows.filter((row) => row.year === latest.year && row.month <= latest.month);
  const previousYear = rows.filter((row) => row.year === latest.year - 1 && row.month <= latest.month);
  const prior11 = rows.slice(-12, -1);
  const sameMonth = rows.filter((row) => row.month === latest.month && row.year < latest.year);
  let streak = 0;
  for (let index = rows.length - 1; index > 0; index -= 1) {
    if (!finite(rows[index].yoy) || !finite(rows[index - 1].yoy) || rows[index].yoy <= rows[index - 1].yoy) break;
    streak += 1;
  }
  return {
    months: rows.length,
    period: latest.period,
    yoy: latest.yoy,
    mom: latest.mom,
    avg3Yoy: mean(rows.slice(-3).map((row) => row.yoy)),
    ytdYoy: sum(previousYear.map((row) => row.revenue)) ? (sum(currentYear.map((row) => row.revenue)) / sum(previousYear.map((row) => row.revenue)) - 1) * 100 : null,
    acceleration3: finite(latest.yoy) && finite(rows.at(-3)?.yoy) ? (latest.yoy - rows.at(-3).yoy) / 2 : null,
    consecutiveAcceleration: streak,
    new12MonthHigh: prior11.length ? latest.revenue > Math.max(...prior11.map((row) => row.revenue)) : null,
    sameMonthRecord: sameMonth.length ? latest.revenue > Math.max(...sameMonth.map((row) => row.revenue)) : null,
  };
}

function financialAsOf(history, asOf) {
  const rows = history.filter((row) => row.availableAt && row.availableAt <= asOf);
  const latest = rows.at(-1) || {};
  const yearAgo = rows.at(-5) || {};
  const growth = (current, prior) => finite(current) && finite(prior) && prior !== 0 ? (current / Math.abs(prior) - 1) * 100 : null;
  return {
    quarters: rows.length,
    ...latest,
    epsYoy: growth(latest.eps, yearAgo.eps),
    revenueYoy: growth(latest.revenue, yearAgo.revenue),
    grossMarginYoyChange: finite(latest.grossMargin) && finite(yearAgo.grossMargin) ? latest.grossMargin - yearAgo.grossMargin : null,
    operatingMarginYoyChange: finite(latest.operatingMargin) && finite(yearAgo.operatingMargin) ? latest.operatingMargin - yearAgo.operatingMargin : null,
    inventoryYoy: growth(latest.inventory, yearAgo.inventory),
    receivablesYoy: growth(latest.receivables, yearAgo.receivables),
  };
}

function institutionalAsOf(history, asOf) {
  const rows = history.filter((row) => row.date <= asOf);
  const cumulative = (key, period) => sum(rows.slice(-period).map((row) => row[key]));
  const streak = (key) => {
    let count = 0;
    for (let index = rows.length - 1; index >= 0; index -= 1) {
      if (rows[index][key] <= 0) break;
      count += 1;
    }
    return count;
  };
  return {
    days: rows.length,
    foreign20: cumulative("foreign", 20),
    trust20: cumulative("trust", 20),
    inst5: cumulative("inst", 5),
    inst20: cumulative("inst", 20),
    foreignStreak: streak("foreign"),
    trustStreak: streak("trust"),
    intensity5: mean(rows.slice(-5).map((row) => row.intensity)),
  };
}

function marginAsOf(history, asOf) {
  const rows = history.filter((row) => row.date <= asOf);
  const latest = rows.at(-1) || {};
  return {
    days: rows.length,
    marginChange5: rows.length > 5 ? latest.marginBalance - rows.at(-6).marginBalance : null,
    marginChange20: rows.length > 20 ? latest.marginBalance - rows.at(-21).marginBalance : null,
    marginUsage: latest.marginLimit ? latest.marginBalance / latest.marginLimit * 100 : null,
  };
}

export function deepAsOf(deep, asOf) {
  const priceHistory = (deep.priceHistory || []).filter((row) => row.date <= asOf);
  const price = deepDataInternals.priceSummary(priceHistory, []);
  const output = { ...deep, priceHistory, price, fetchedAt: asOf };
  if (deep.instrumentType !== "ETF") {
    output.revenue = revenueAsOf(deep.revenueHistory || [], asOf);
    output.financial = financialAsOf(deep.financial?.history || [], asOf);
    output.institutional = institutionalAsOf(deep.institutional?.history || [], asOf);
    output.margin = marginAsOf(deep.margin?.history || [], asOf);
  }
  return output;
}

export function backtestUniverse({ candidates, horizons = [5, 10, 20], step = 5, minimumHistory = 120 }) {
  const dateSet = new Set();
  candidates.forEach(({ deep }) => (deep.priceHistory || []).slice(minimumHistory, -Math.max(...horizons)).forEach((row, index) => {
    if (index % step === 0) dateSet.add(row.date);
  }));
  const dates = [...dateSet].sort();
  const samples = [];
  for (const date of dates) {
    const ranked = candidates.map(({ stock, deep, risk, context }) => {
      const sliced = deepAsOf(deep, date);
      const priceRow = sliced.priceHistory.at(-1);
      if (!priceRow || sliced.priceHistory.length < minimumHistory) return null;
      const historicalStock = { ...stock, close: priceRow.close, volume: priceRow.volume, value: priceRow.value };
      return { stock: historicalStock, deep: sliced, result: scoreOpportunity({ stock: historicalStock, deep: sliced, risk, context }) };
    }).filter(Boolean).filter((entry) => !entry.result.risk.hardExcluded).sort((a, b) => b.result.score - a.result.score).slice(0, 10);
    for (const entry of ranked) {
      const rows = entry.deep.priceHistory;
      const start = rows.length - 1;
      const original = candidates.find((candidate) => candidate.stock.symbol === entry.stock.symbol)?.deep.priceHistory || [];
      const actualIndex = original.findIndex((row) => row.date === rows[start].date);
      const returns = {};
      const excursions = {};
      horizons.forEach((horizon) => {
        const future = original[actualIndex + horizon];
        const window = original.slice(actualIndex + 1, actualIndex + horizon + 1);
        returns[horizon] = future ? (future.close / rows[start].close - 1) * 100 : null;
        excursions[horizon] = window.length ? {
          mfe: Math.max(...window.map((row) => row.high / rows[start].close - 1)) * 100,
          mae: Math.min(...window.map((row) => row.low / rows[start].close - 1)) * 100,
        } : null;
      });
      samples.push({ date, symbol: entry.stock.symbol, group: entry.result.group, score: entry.result.score, confidence: entry.result.confidence, returns, excursions });
    }
  }
  const summary = {};
  horizons.forEach((horizon) => {
    const values = samples.map((sample) => sample.returns[horizon]).filter(finite);
    const excursionRows = samples.map((sample) => sample.excursions[horizon]).filter(Boolean);
    summary[horizon] = {
      count: values.length,
      averageReturn: round(mean(values)),
      winRate: values.length ? round(values.filter((value) => value > 0).length / values.length * 100) : null,
      averageMfe: round(mean(excursionRows.map((row) => row.mfe))),
      averageMae: round(mean(excursionRows.map((row) => row.mae))),
    };
  });
  return { generatedAt: new Date().toISOString(), noLookAhead: true, horizons: summary, samples };
}

export const engineInternals = { interpolate, companyCategories, etfCategories, riskAssessment };
