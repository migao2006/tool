import assert from "node:assert/strict";
import { deepDataInternals } from "../src/deep-data.js";

const income = [];
const balance = [];
const cash = [];
const periods = [
  ["2025-03-31", 100, 30, 50, 10],
  ["2025-06-30", 120, 40, 130, 25],
  ["2025-09-30", 140, 50, 210, 45],
  ["2025-12-31", 160, 60, 300, 70],
  ["2026-03-31", 180, 70, 90, 20],
];

for (const [date, revenue, netIncome, cumulativeOcf, cumulativeCapex] of periods) {
  income.push(
    { date, type: "Revenue", value: revenue, origin_name: "營業收入" },
    { date, type: "GrossProfit", value: revenue * 0.4, origin_name: "營業毛利" },
    { date, type: "OperatingIncome", value: revenue * 0.2, origin_name: "營業利益" },
    { date, type: "IncomeAfterTaxes", value: netIncome, origin_name: "本期淨利（淨損）" },
    { date, type: "EPS", value: netIncome / 50, origin_name: "基本每股盈餘（元）" },
  );
  balance.push(
    { date, type: "TotalAssets", value: 1_000, origin_name: "資產總額" },
    { date, type: "TotalLiabilities", value: 400, origin_name: "負債總額" },
    { date, type: "Equity", value: 600, origin_name: "權益總額" },
    { date, type: "CurrentAssets", value: 300, origin_name: "流動資產" },
    { date, type: "CurrentLiabilities", value: 100, origin_name: "流動負債" },
  );
  cash.push(
    { date, type: "CashFlowsFromOperatingActivities", value: cumulativeOcf, origin_name: "營業活動之淨現金流入（流出）" },
    { date, type: "PropertyAndPlantAndEquipment", value: -cumulativeCapex, origin_name: "取得不動產、廠房及設備" },
  );
}

const result = deepDataInternals.financialSummary(income, balance, cash);
assert.equal(result.period, "2026 Q1");
assert.equal(result.eps, 1.4, "income statement values must remain single-quarter values");
assert.equal(result.history.at(-2).netIncome, 60, "Q4 net income must not be differenced again");
assert.equal(result.history.at(-4).operatingCashFlow, 80, "YTD cash flow must be converted to a standalone quarter");
assert.equal(result.latestQuarterOperatingCashFlow, 90);
assert.equal(result.ttmNetIncome, 220);
assert.equal(result.ttmOperatingCashFlow, 340);
assert.equal(result.ttmFreeCashFlow, 260);
assert.equal(result.cashConversion, 1.5455);
assert.equal(result.cashConversionBasis, "TTM");

console.log("Deep-data tests passed: single-quarter income, cumulative cash differencing, and TTM cash conversion");
