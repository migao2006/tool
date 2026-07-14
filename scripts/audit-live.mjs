import { readBackendHistory } from "../src/backend-store.js";

const endpoints = {
  twseOpenPrice: "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
  tpexPrice: "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
  tpexValuation: "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis",
  tpexInstitutional: "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading",
  tpexMargin: "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance",
  twseRevenue: "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
  tpexRevenue: "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O",
  twseDisposition: "https://openapi.twse.com.tw/v1/announcement/punish",
  twseAttention: "https://openapi.twse.com.tw/v1/announcement/notice",
  twseChangedTrading: "https://openapi.twse.com.tw/v1/exchangeReport/TWT85U",
  twseSuspended: "https://openapi.twse.com.tw/v1/exchangeReport/TWTAWU",
  tpexDisposition: "https://www.tpex.org.tw/openapi/v1/tpex_disposal_information",
  tpexAttention: "https://www.tpex.org.tw/openapi/v1/tpex_trading_warning_information",
  tpexChangedTrading: "https://www.tpex.org.tw/openapi/v1/tpex_cmode",
  tpexSuspended: "https://www.tpex.org.tw/openapi/v1/tpex_spendi_today",
  twseIndex: "https://openapi.twse.com.tw/v1/indicesReport/MI_5MINS_HIST",
  tpexIndex: "https://www.tpex.org.tw/openapi/v1/tpex_index",
  etfProfiles: "https://openapi.twse.com.tw/v1/opendata/t187ap47_L",
};

const rocDate = (value) => {
  const raw = String(value || "").replaceAll("-", "").replaceAll("/", "");
  if (/^\d{8}$/.test(raw)) return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
  if (/^\d{7}$/.test(raw)) return `${Number(raw.slice(0, 3)) + 1911}-${raw.slice(3, 5)}-${raw.slice(5, 7)}`;
  return "";
};

async function get(name, url) {
  try {
    const response = await fetch(url, {
      headers: { accept: "application/json", "user-agent": "TaiwanStockSmartPicker-Audit/16.3" },
      signal: AbortSignal.timeout(45_000),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  } catch (error) {
    throw new Error(`${name}: ${error?.name === 'TimeoutError' ? '45 秒逾時' : error.message}`, { cause: error });
  }
}

const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const resultEntries = [];
for (const [name, url] of Object.entries(endpoints)) {
  if (resultEntries.length) await sleep(1300);
  resultEntries.push([name, await get(name, url)]);
}
const results = Object.fromEntries(resultEntries);
const arrays = Object.fromEntries(
  Object.entries(results).map(([name, payload]) => [name, Array.isArray(payload) ? payload : payload.data || []]),
);

const tpexPriceDate = rocDate(arrays.tpexPrice[0]?.Date);
const twseOpenPriceDate = rocDate(arrays.twseOpenPrice[0]?.Date);
const latestTradeDate = [twseOpenPriceDate, tpexPriceDate].filter(Boolean).sort().at(-1);
const target = latestTradeDate.replaceAll("-", "");
await sleep(1500);
const twsePrice = await get("twsePrice", `https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=${target}&type=ALLBUT0999&response=json`);
await sleep(1500);
const twseValuation = await get("twseValuation", `https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date=${target}&selectType=ALL&response=json`);
await sleep(1500);
const twseInstitutional = await get("twseInstitutional", `https://www.twse.com.tw/rwd/zh/fund/T86?date=${target}&response=json&selectType=ALLBUT0999`);
const twseInstitutionalDate = rocDate(twseInstitutional.date);

const twsePriceTable = twsePrice.tables?.find((table) => String(table.title || "").includes("每日收盤行情"));
await sleep(1500);
const otcHistory = { ...(await readBackendHistory("6613", 280)), market: "上櫃" };
const report = [
  { source: "TWSE 上市行情（指定日）", date: rocDate(twsePrice.date), rows: twsePriceTable?.data?.length || 0 },
  { source: "TWSE 上市估值（指定日）", date: rocDate(twseValuation.date), rows: twseValuation.data?.length || 0 },
  { source: "TWSE 三大法人", date: twseInstitutionalDate, rows: twseInstitutional.data?.length || 0 },
  { source: "TWSE OpenAPI 行情備援", date: rocDate(arrays.twseOpenPrice[0]?.Date), rows: arrays.twseOpenPrice.length },
  { source: "TPEx 上櫃行情", date: tpexPriceDate, rows: arrays.tpexPrice.length },
  { source: "TPEx 上櫃估值", date: rocDate(arrays.tpexValuation[0]?.Date), rows: arrays.tpexValuation.length },
  { source: "TPEx 三大法人", date: rocDate(arrays.tpexInstitutional[0]?.Date), rows: arrays.tpexInstitutional.length },
  { source: "TPEx 融資融券", date: rocDate(arrays.tpexMargin[0]?.Date), rows: arrays.tpexMargin.length },
  { source: "TWSE 月營收", date: rocDate(arrays.twseRevenue[0]?.出表日期), period: arrays.twseRevenue[0]?.資料年月, rows: arrays.twseRevenue.length },
  { source: "TPEx 月營收", date: rocDate(arrays.tpexRevenue[0]?.出表日期), period: arrays.tpexRevenue[0]?.資料年月, rows: arrays.tpexRevenue.length },
  { source: "TWSE 處置／注意／變更／停牌", rows: arrays.twseDisposition.length + arrays.twseAttention.length + arrays.twseChangedTrading.length + arrays.twseSuspended.length },
  { source: "TPEx 處置／注意／變更／停牌", rows: arrays.tpexDisposition.length + arrays.tpexAttention.length + arrays.tpexChangedTrading.length + arrays.tpexSuspended.length },
  { source: "TWSE 大盤指數歷史", date: rocDate(arrays.twseIndex.at(-1)?.Date), rows: arrays.twseIndex.length },
  { source: "TPEx 櫃買指數歷史", date: rocDate(arrays.tpexIndex.at(-1)?.Date), rows: arrays.tpexIndex.length },
  { source: "TWSE ETF 基本資料", date: rocDate(arrays.etfProfiles[0]?.出表日期), rows: arrays.etfProfiles.length },
  { source: "Supabase／FinMind 原始行情（含公司行動隔離）：上櫃 6613", date: otcHistory.period, rows: otcHistory.count },
];

const requiredTpexInstitutional = [
  "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference",
  "SecuritiesInvestmentTrustCompanies-Difference",
  "Dealers-Difference",
  "TotalDifference",
];
for (const field of requiredTpexInstitutional) {
  if (!(field in (arrays.tpexInstitutional[0] || {}))) throw new Error(`TPEx 法人欄位已變更：缺少 ${field}`);
}
if (!("營業收入-當月營收" in (arrays.twseRevenue[0] || {}))) {
  throw new Error("TWSE 月營收欄位已變更：缺少 營業收入-當月營收");
}
if (!twsePriceTable?.data?.length) throw new Error("TWSE 指定交易日行情無資料");
if (!arrays.twseIndex.length || !arrays.tpexIndex.length) throw new Error("市場指數歷史端點無資料");
if (!arrays.etfProfiles.length) throw new Error("ETF 基本資料端點無資料");
if (otcHistory.count < 120 || otcHistory.market !== "上櫃") throw new Error("上櫃歷史日線市場路由失敗");

console.table(report);
console.log(`官方資料稽核完成；最新交易日 ${latestTradeDate}`);
