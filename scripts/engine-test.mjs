import assert from "node:assert/strict";
import { scoreOpportunity } from "../src/opportunity-engine.js";

const stock = {
  symbol: "2330",
  name: "完整資料測試",
  market: "上市",
  instrumentType: "股票",
  industry: "半導體業",
  close: 100,
  change: 1.5,
  volume: 20_000,
  value: 2_000_000_000,
  pe: 18,
  pb: 3,
  yield: 3,
};

const price = {
  rows: 280,
  sufficient: true,
  lastClose: 100,
  ma20: 96,
  ma60: 91,
  ma120: 86,
  ma20Slope5: 2,
  relative20: 6,
  breakout20: true,
  volumeRatio: 1.6,
  upDownVolumeRatio: 1.5,
  rsi14: 61,
  distanceMa20: 4.2,
  distanceHigh20: -1,
  macdHistogram: 1.2,
  marketReturn20: 3,
  atrPct: 2.2,
  limitUpStreak: 0,
  jumpAnomaly: false,
};

const completeDeep = {
  instrumentType: "股票",
  missing: [],
  price,
  revenue: {
    months: 36,
    continuousMonths: 36,
    yoy: 25,
    avg3Yoy: 22,
    ytdYoy: 18,
    acceleration3: 7,
    consecutiveAcceleration: 3,
    new12MonthHigh: true,
    sameMonthRecord: true,
    postRelease5: 3,
  },
  financial: {
    quarters: 12,
    continuousQuarters: 12,
    sourceCoverage: { incomeRows: 120, balanceRows: 140, cashflowRows: 80 },
    epsYoy: 28,
    operatingMarginYoyChange: 2,
    cashConversion: 1.1,
    operatingCashFlow: 120,
    inventoryYoy: 8,
    receivablesYoy: 9,
    revenueYoy: 20,
    debtRatio: 35,
  },
  institutional: {
    days: 63,
    foreign20: 8_000,
    foreignStreak: 4,
    trust20: 1_200,
    trustStreak: 3,
    intensity5: 3.5,
    inst5: 2_000,
  },
  margin: { days: 63, marginChange5: -100, marginChange20: -400, marginUsage: 14 },
  holdings: { large400Ratio: 68, retail10Ratio: 18 },
};

const context = {
  peValuePercentile: 72,
  pbValuePercentile: 65,
  marketBreadth: 62,
  industryBreadth: 66,
  industryRelativeChange: 2,
};

const complete = scoreOpportunity({ stock, deep: completeDeep, risk: { coverageComplete: true }, context });
assert.equal(complete.group, "listed");
assert.equal(complete.categories.length, 5);
assert.ok(complete.confidence >= 95, `complete confidence was ${complete.confidence}`);
assert.ok(complete.score >= 60, `complete score was ${complete.score}`);
assert.equal(complete.official, true);

const unverifiedRiskCoverage = scoreOpportunity({
  stock,
  deep: completeDeep,
  risk: { coverageComplete: false },
  context,
});
assert.equal(unverifiedRiskCoverage.official, false, "an incomplete official risk list must block formal ranking");

const staleFundamentals = scoreOpportunity({
  stock,
  deep: {
    ...completeDeep,
    sourceDiagnostics: {
      revenue: { status: "stale-source-period", actualPeriod: "2026-05", expectedPeriod: "2026-06" },
    },
  },
  risk: { coverageComplete: true },
  context,
});
assert.equal(staleFundamentals.official, false, "a stale essential period must not enter the formal ranking");
assert.equal(staleFundamentals.freshnessVerified, false);

// Missing fundamentals are removed from the denominator of the score itself,
// but remain visible in confidence; they must never silently become zeroes.
const incompleteDeep = { instrumentType: "股票", price, missing: ["36 月營收", "12 季財報"] };
const incomplete = scoreOpportunity({ stock, deep: incompleteDeep, risk: { coverageComplete: true }, context });
assert.equal(incomplete.categories.find((row) => row.key === "growth").score, null);
assert.ok(incomplete.baseScore > 0);
assert.ok(incomplete.confidence < complete.confidence);
assert.equal(incomplete.official, false);

const hardExcluded = scoreOpportunity({
  stock,
  deep: completeDeep,
  risk: { coverageComplete: true, hardExcluded: true, flags: ["處置股票"] },
  context,
});
assert.equal(hardExcluded.risk.hardExcluded, true);
assert.equal(hardExcluded.official, false);
assert.match(hardExcluded.risk.hardReasons.join("、"), /處置股票/);

const dangerous = scoreOpportunity({
  stock,
  deep: {
    ...completeDeep,
    price: { ...price, limitUpStreak: 3, distanceMa20: 28, rsi14: 88, atrPct: 12 },
    revenue: { ...completeDeep.revenue, yoy: 30 },
    financial: {
      ...completeDeep.financial,
      epsYoy: 25,
      operatingMarginYoyChange: -8,
      operatingCashFlow: -100,
      inventoryYoy: 80,
      receivablesYoy: 75,
      revenueYoy: 10,
      debtRatio: 88,
    },
  },
  risk: { coverageComplete: true, attention: true },
  context,
});
assert.equal(dangerous.risk.deduction, 30);

const otcCashSwing = scoreOpportunity({
  stock: { ...stock, symbol: "3402", name: "上櫃現金流測試", market: "上櫃" },
  deep: {
    ...completeDeep,
    financial: {
      ...completeDeep.financial,
      cashConversion: -0.35,
      ttmOperatingCashFlow: -188,
      operatingCashFlow: -188,
    },
  },
  risk: { coverageComplete: true },
  context,
});
assert.equal(otcCashSwing.group, "otc");
assert.equal(otcCashSwing.risk.deduction, 2, "a mild TPEx TTM cash outflow should not receive the old six-point one-quarter penalty");
assert.match(otcCashSwing.risk.flags.join("、"), /近四季營業現金流為負/);

const etf = scoreOpportunity({
  stock: { ...stock, symbol: "0050", name: "ETF 測試", instrumentType: "ETF", industry: "ETF", pe: null, pb: null },
  deep: {
    instrumentType: "ETF",
    price,
    etf: {
      units: 500_000_000,
      fundType: "指數股票型",
      benchmark: "臺灣50指數",
      leveraged: false,
      inverse: false,
      foreignExposure: false,
    },
    missing: ["即時淨值折溢價", "追蹤誤差", "經理費／內扣費用", "成分股集中度"],
  },
  risk: { coverageComplete: true },
  context,
});
assert.equal(etf.group, "etf");
assert.deepEqual(etf.categories.map((row) => row.key), ["trend", "liquidity", "structure", "tracking", "market"]);
assert.equal(etf.categories.some((row) => ["growth", "chip", "valuation"].includes(row.key)), false);
assert.equal(etf.categories.find((row) => row.key === "tracking").score, null);

console.log("Opportunity engine tests passed: renormalization, confidence gate, hard risks, capped deductions, and ETF separation");
