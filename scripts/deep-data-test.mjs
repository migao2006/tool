import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { deepDataInternals } from "../src/deep-data.js";

assert.equal(deepDataInternals.finmindCooldownMs({ status: 401 }), 60 * 60 * 1_000);
assert.equal(
  deepDataInternals.finmindCooldownMs({ status: 400, message: "Invalid access token" }),
  60 * 60 * 1_000,
  "credential failures returned inside a FinMind payload must open the circuit",
);
assert.equal(deepDataInternals.finmindCooldownMs({ status: 429, retryAfter: 120 }), 120 * 1_000);
assert.equal(deepDataInternals.finmindCooldownMs({ status: 429, retryAfter: 15 }), 60 * 1_000);
assert.equal(
  deepDataInternals.finmindCooldownMs({ status: 400, message: "Dataset not available" }),
  0,
  "a dataset-specific 400 must not pause unrelated FinMind datasets",
);

const deepDataSource = await readFile(new URL("../src/deep-data.js", import.meta.url), "utf8");
assert.match(deepDataSource, /finmind\("TaiwanStockPrice", symbol/);
assert.doesNotMatch(
  deepDataSource,
  /finmind\("TaiwanStockPriceAdj", symbol/,
  "the paid PriceAdj dataset must not make free-level technical analysis fail",
);

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
    { date, type: "AccountsReceivableNet", value: revenue * 2, origin_name: "應收帳款淨額" },
    { date, type: "AccountsReceivableNet_per", value: 19.29, origin_name: "應收帳款淨額" },
    { date, type: "BillsReceivableNet", value: revenue / 2, origin_name: "應收票據淨額" },
    { date, type: "BillsReceivableNet_per", value: 3.5, origin_name: "應收票據淨額" },
  );
  cash.push(
    { date, type: "CashFlowsFromOperatingActivities", value: cumulativeOcf, origin_name: "營業活動之淨現金流入（流出）" },
    { date, type: "PropertyAndPlantAndEquipment", value: -cumulativeCapex, origin_name: "取得不動產、廠房及設備" },
  );
}

const result = deepDataInternals.financialSummary(income, balance, cash);
assert.equal(result.period, "2026 Q1");
assert.equal(result.revenue, 180, "financial summary must expose the latest quarterly revenue");
assert.equal(result.eps, 1.4, "income statement values must remain single-quarter values");
assert.equal(result.history.at(-2).netIncome, 60, "Q4 net income must not be differenced again");
assert.equal(result.history.at(-4).operatingCashFlow, 80, "YTD cash flow must be converted to a standalone quarter");
assert.equal(result.latestQuarterOperatingCashFlow, 90);
assert.equal(result.ttmNetIncome, 220);
assert.equal(result.ttmOperatingCashFlow, 340);
assert.equal(result.ttmFreeCashFlow, 260);
assert.equal(result.cashConversion, 1.5455);
assert.equal(result.cashConversionBasis, "TTM");
assert.equal(result.continuousQuarters, 5);
assert.deepEqual(result.sourceCoverage, { incomeRows: income.length, balanceRows: balance.length, cashflowRows: cash.length });
assert.equal(result.history.at(-1).receivables, 450, "receivable amounts must be summed without `_per` ratios overwriting them");

const mergedQuote = deepDataInternals.mergeCurrentQuote([
  { date: "2026-07-10", open: 98, high: 101, low: 97, close: 100, volume: 1000 },
], {
  trade_date: "2026-07-13", open: 101, high: 105, low: 100, close: 104, volume: 2000,
});
assert.equal(mergedQuote.at(-1).date, "2026-07-13");
assert.equal(mergedQuote.at(-1).close, 104, "the official same-day quote must close FinMind's publication lag");
assert.equal(deepDataInternals.validSymbol("00980A"), true);
assert.equal(deepDataInternals.isEtfSymbol("00631L"), true);
assert.equal(deepDataInternals.isEtfSymbol("00679B"), true);
assert.deepEqual(deepDataInternals.etfDirectionFlags({
  name: "國泰臺灣加權正2",
  type: "槓桿/反向指數股票型基金",
  benchmark: "臺灣證券交易所發行量加權股價日報酬正向兩倍指數",
}), { leveraged: true, inverse: false }, "a generic MOPS umbrella type must not mark long 2x ETFs as inverse");
assert.deepEqual(deepDataInternals.etfDirectionFlags({
  name: "元大台灣50反1",
  type: "槓桿/反向指數股票型基金",
  benchmark: "臺灣50指數單日反向一倍報酬指數",
}), { leveraged: false, inverse: true });

const taiexSnapshot = deepDataInternals.latestIndexSnapshot([
  { Date: "1150713", ClosingIndex: "23,000.00" },
  { Date: "1150714", ClosingIndex: "23,230.00" },
], { code: "taiex", name: "加權指數", source: "TWSE OpenAPI", closeField: "ClosingIndex" });
assert.deepEqual(taiexSnapshot, {
  code: "taiex", name: "加權指數", dataDate: "2026-07-14", value: 23230,
  change: 230, changePercent: 1, source: "TWSE OpenAPI",
});

const tpexSnapshot = deepDataInternals.latestIndexSnapshot([
  { Date: "20260715", Close: "250.00", Change: "5.00" },
], { code: "tpex", name: "櫃買指數", source: "TPEx OpenAPI", closeField: "Close", changeField: "Change" });
assert.equal(tpexSnapshot.dataDate, "2026-07-15");
assert.equal(tpexSnapshot.changePercent, 2.04);

const misTaiexSnapshot = deepDataInternals.selectMisIndex({ msgArray: [{
  ex: "tse", d: "20260715", z: "45631.59", y: "44737.95",
}] }, { exchange: "tse", code: "taiex", name: "加權指數" });
assert.deepEqual(misTaiexSnapshot, {
  code: "taiex", name: "加權指數", dataDate: "2026-07-15", value: 45631.59,
  change: 893.64, changePercent: 2, source: "TWSE MIS",
});
assert.equal(
  deepDataInternals.freshestSnapshot(misTaiexSnapshot, taiexSnapshot),
  misTaiexSnapshot,
  "the freshest valid market snapshot must win over a stale OpenAPI snapshot",
);
assert.deepEqual(
  deepDataInternals.mergeBenchmarkSnapshot([{ date: "2026-07-14", close: 44737.95 }], misTaiexSnapshot),
  [{ date: "2026-07-14", close: 44737.95 }, { date: "2026-07-15", close: 45631.59 }],
);

const finmindTxSnapshot = deepDataInternals.selectFinmindTx([
  { date: "2026-07-15", futures_id: "TX", contract_date: "202607", trading_session: "position", close: 45830, spread: 1040, spread_per: 2.32, volume: 30555, settlement_price: 0, open_interest: 10992 },
  { date: "2026-07-15", futures_id: "TX", contract_date: "202608", trading_session: "position", close: 46050, spread: 905, spread_per: 2, volume: 45252, settlement_price: 46066, open_interest: 101230 },
  { date: "2026-07-15", futures_id: "TX", contract_date: "202607", trading_session: "after_market", close: 45015, spread: 225, spread_per: 0.5, volume: 35067, settlement_price: 0, open_interest: 0 },
]);
assert.deepEqual(finmindTxSnapshot, {
  code: "tx", name: "台指期", dataDate: "2026-07-15", value: 46050,
  change: 905, changePercent: 2, contractMonth: "202608", session: "regular",
  volume: 45252, settlementPrice: 46066, openInterest: 101230,
  source: "FinMind TaiwanFuturesDaily",
});

const txSnapshot = deepDataInternals.selectTaifexTx([
  { Date: "20260714", Contract: "TX", "ContractMonth(Week)": "202607W3", Last: "23010", Change: "10", "%": "0.04%", Volume: "999999", SettlementPrice: "23000", OpenInterest: "1" },
  { Date: "20260714", Contract: "TX", "ContractMonth(Week)": "202607", Last: "23000", Change: "100", "%": "0.44%", Volume: "1000", SettlementPrice: "22990", OpenInterest: "500" },
  { Date: "20260714", Contract: "TX", "ContractMonth(Week)": "202608", Last: "23120", Change: "120", "%": "0.52%", Volume: "3000", SettlementPrice: "23100", OpenInterest: "800" },
  { Date: "20260714", Contract: "TX", "ContractMonth(Week)": "202609", Last: "23200", Change: "130", "%": "0.56%", Volume: "5000", SettlementPrice: "NULL", OpenInterest: "900" },
]);
assert.deepEqual(txSnapshot, {
  code: "tx", name: "台指期", dataDate: "2026-07-14", value: 23120,
  change: 120, changePercent: 0.52, contractMonth: "202608", session: "regular",
  volume: 3000, settlementPrice: 23100, openInterest: 800, source: "TAIFEX OpenAPI",
});

const splitLikeSeries = Array.from({ length: 40 }, (_, index) => ({
  date: new Date(Date.UTC(2026, 0, index + 1)).toISOString().slice(0, 10),
  open: index < 20 ? 100 : 50,
  high: index < 20 ? 101 : 51,
  low: index < 20 ? 99 : 49,
  close: index < 20 ? 100 : 50,
  volume: 1000,
}));
assert.equal(
  deepDataInternals.priceSummary(splitLikeSeries).jumpAnomaly,
  true,
  "raw free-level prices must quarantine split/capital-reduction discontinuities",
);

const financeIncome = deepDataInternals.financialSummary([
  { date: "2026-03-31", type: "Income", value: 500, origin_name: "收益" },
  { date: "2026-03-31", type: "IncomeAfterTaxes", value: 80, origin_name: "本期淨利" },
], [], []);
assert.equal(financeIncome.revenue, 500, "finance-sector `Income/收益` must be recognized as quarterly revenue");
assert.equal(financeIncome.revenueBasis, "finance-income");

const bankIncome = deepDataInternals.financialSummary([
  { date: "2026-03-31", type: "NetInterestIncome", value: 350, origin_name: "利息淨收益" },
  { date: "2026-03-31", type: "NetNonInterestIncome", value: 150, origin_name: "非利息淨收益" },
  { date: "2026-03-31", type: "IncomeAfterTaxes", value: 60, origin_name: "本期淨利" },
], [], []);
assert.equal(bankIncome.revenue, 500);
assert.equal(bankIncome.revenueBasis, "bank-net-income-components");

const insurance = deepDataInternals.financialSummary([
  { date: "2026-03-31", type: "InsuranceServiceResult", value: 120, origin_name: "保險服務結果" },
  { date: "2026-03-31", type: "IncomeAfterTaxes", value: 40, origin_name: "本期淨利" },
], [], []);
assert.equal(insurance.revenue, null);
assert.equal(insurance.revenueStatus, "source-not-comparable");

const lossIncome = [];
const lossCash = [];
for (const [date, cumulativeOcf] of [["2025-06-30", -10], ["2025-09-30", -20], ["2025-12-31", -30], ["2026-03-31", -10]]) {
  lossIncome.push(
    { date, type: "Revenue", value: 100, origin_name: "營業收入" },
    { date, type: "IncomeAfterTaxes", value: -10, origin_name: "本期淨損" },
  );
  lossCash.push({
    date, type: "CashProvidedByOperatingActivities", value: cumulativeOcf,
    origin_name: "營業活動之淨現金流入（流出）",
  });
}
const lossResult = deepDataInternals.financialSummary(lossIncome, [], lossCash);
assert.equal(lossResult.ttmNetIncome, -40);
assert.equal(lossResult.cashConversion, null, "negative earnings must never turn negative OCF into a positive conversion score");
assert.equal(lossResult.cashConversionBasis, "TTM-nonpositive-net-income");

const revenueGap = deepDataInternals.revenueSummary(deepDataInternals.normalizeRevenue([
  { date: "2026-02-10", revenue_year: 2026, revenue_month: 1, revenue: 100 },
  { date: "2026-04-10", revenue_year: 2026, revenue_month: 3, revenue: 130 },
  { date: "2026-05-10", revenue_year: 2026, revenue_month: 4, revenue: 150 },
]), []);
assert.equal(revenueGap.continuousMonths, 2);
assert.equal(revenueGap.avg3Yoy, null, "a missing calendar month must not masquerade as a three-month average");

const quarterGap = deepDataInternals.financialSummary([
  { date: "2025-03-31", type: "Revenue", value: 100, origin_name: "營業收入" },
  { date: "2025-06-30", type: "Revenue", value: 110, origin_name: "營業收入" },
  { date: "2025-12-31", type: "Revenue", value: 130, origin_name: "營業收入" },
  { date: "2026-03-31", type: "Revenue", value: 140, origin_name: "營業收入" },
], [], []);
assert.equal(quarterGap.continuousQuarters, 2);
assert.equal(quarterGap.ttmOperatingCashFlow, null, "non-consecutive quarters must not form a fake TTM window");

console.log("Deep-data tests passed: financial semantics, current-quote merge, and alphanumeric ETF symbols");
