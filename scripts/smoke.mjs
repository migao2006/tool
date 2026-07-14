import assert from "node:assert/strict";
import worker from "../worker/index.js";

const listedSymbols = Array.from({ length: 25 }, (_, index) => String(1101 + index));
const listedEtfSymbols = ["0050", "006208"];
const listedTradeSymbols = [...listedSymbols, ...listedEtfSymbols];
const otcSymbols = Array.from({ length: 25 }, (_, index) => String(4101 + index));

const listedOpenApi = listedTradeSymbols.map((Code, index) => ({
  Date: "1150709",
  Code,
  Name: listedEtfSymbols.includes(Code) ? `ETF測試${index + 1}` : `上市測試${index + 1}`,
  ClosingPrice: "99",
  Change: "0",
  OpeningPrice: "99",
  HighestPrice: "100",
  LowestPrice: "98",
  TradeVolume: "900000",
  TradeValue: "90000000",
  Transaction: "4500",
}));

const listedWebRows = listedTradeSymbols.map((symbol, index) => [
  symbol,
  listedEtfSymbols.includes(symbol) ? `ETF測試${index + 1}` : `上市測試${index + 1}`,
  "1,000,000",
  "5,000",
  "100,000,000",
  "100",
  "102",
  "98",
  "100",
  index === 0 ? "<p style= color:green>-</p>" : "<p style= color:red>+</p>",
  "1",
  "99",
  "10",
  "100",
  "20",
  "15",
]);

const otc = otcSymbols.map((SecuritiesCompanyCode, index) => ({
  Date: "1150713",
  SecuritiesCompanyCode,
  CompanyName: `上櫃測試${index + 1}`,
  Close: "50",
  Change: "0.5",
  Open: "49.5",
  High: "51",
  Low: "49",
  TradingShares: "600000",
  TransactionAmount: "30000000",
  TransactionNumber: "2000",
}));

const json = (payload, status = 200) =>
  new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });

const fullFetch = async (input) => {
  const url = String(input);
  if (url.includes("api.finmindtrade.com") && url.includes("dataset=TaiwanStockPrice")) {
    assert.doesNotMatch(url, /TaiwanStockPriceAdj/, "the paid adjusted-price dataset must not block free-level technical history");
    const symbol = new URL(url).searchParams.get("data_id");
    return json({
      status: 200,
      msg: "success",
      data: Array.from({ length: 130 }, (_, index) => ({
        date: new Date(Date.UTC(2026, 0, 1 + index)).toISOString().slice(0, 10),
        stock_id: symbol,
        open: 50 + index * 0.1,
        max: 51 + index * 0.1,
        min: 49 + index * 0.1,
        close: 50.5 + index * 0.1,
        Trading_Volume: 600_000,
        Trading_money: 30_000_000,
        Trading_turnover: 2_000,
      })),
    });
  }
  if (url.includes("afterTrading/MI_INDEX")) {
    return json({
      stat: "OK",
      date: "20260713",
      tables: [
        {
          title: "115年07月13日 每日收盤行情(全部)",
          fields: [
            "證券代號",
            "證券名稱",
            "成交股數",
            "成交筆數",
            "成交金額",
            "開盤價",
            "最高價",
            "最低價",
            "收盤價",
            "漲跌(+/-)",
            "漲跌價差",
            "最後揭示買價",
            "最後揭示買量",
            "最後揭示賣價",
            "最後揭示賣量",
            "本益比",
          ],
          data: listedWebRows,
        },
      ],
    });
  }
  if (url.includes("afterTrading/BWIBBU_d")) {
    return json({
      stat: "OK",
      date: "20260713",
      fields: ["證券代號", "證券名稱", "收盤價", "殖利率(%)", "股利年度", "本益比", "股價淨值比", "財報年/季"],
      data: listedTradeSymbols.map((symbol) => [symbol, "測試", "100", "4", "114", "15", "2", "115/1"]),
    });
  }
  if (url.includes("marginTrading/MI_MARGN")) {
    return json({
      stat: "OK",
      date: "20260709",
      tables: [
        {},
        {
          title: "115年07月09日 融資融券彙總 (股票)",
          fields: ["代號", "名稱", "買進", "賣出", "現金償還", "前日餘額", "今日餘額", "次一營業日限額", "買進", "賣出", "現券償還", "前日餘額", "今日餘額", "次一營業日限額", "資券互抵", "註記"],
          data: listedTradeSymbols.map((symbol) => [symbol, "測試", "30", "5", "3", "100", "122", "999", "1", "2", "1", "18", "18", "999", "0", ""]),
        },
      ],
    });
  }
  if (url.includes("STOCK_DAY_ALL")) return json(listedOpenApi);
  if (url.includes("BWIBBU_ALL")) {
    return json(listedTradeSymbols.map((Code) => ({ Date: "1150709", Code, PEratio: "14", PBratio: "1.8", DividendYield: "3.5" })));
  }
  if (url.includes("t187ap03_L")) {
    return json(listedSymbols.map((公司代號) => ({ 出表日期: "1150713", 公司代號, 產業別: "24" })));
  }
  if (url.includes("exchangeReport/MI_MARGN")) {
    return json(listedTradeSymbols.map((股票代號) => ({ 股票代號, 融資今日餘額: "120", 融資買進: "30", 融資賣出: "5", 融資現金償還: "3", 融券今日餘額: "18", 融券賣出: "2", 融券買進: "1", 融券現券償還: "1" })));
  }
  if (url.includes("fund/T86")) {
    return json({
      stat: "OK",
      date: "20260713",
      title: "115年07月13日 三大法人買賣超日報",
      fields: ["證券代號", "外陸資買賣超股數(不含外資自營商)", "投信買賣超股數", "自營商買賣超股數", "三大法人買賣超股數"],
      data: listedTradeSymbols.map((symbol) => [symbol, "200000", "50000", "-10000", "240000"]),
    });
  }
  if (url.includes("tpex_mainboard_daily_close_quotes")) return json(otc);
  if (url.includes("tpex_mainboard_peratio_analysis")) {
    return json(otcSymbols.map((SecuritiesCompanyCode) => ({ Date: "1150713", SecuritiesCompanyCode, PriceEarningRatio: "12", PriceBookRatio: "1.5", YieldRatio: "5" })));
  }
  if (url.includes("mopsfin_t187ap03_O")) {
    return json(otcSymbols.map((SecuritiesCompanyCode) => ({ Date: "1150713", SecuritiesCompanyCode, SecuritiesIndustryCode: "25" })));
  }
  if (url.includes("tpex_mainboard_margin_balance")) {
    return json(otcSymbols.map((SecuritiesCompanyCode) => ({ Date: "1150709", SecuritiesCompanyCode, MarginPurchaseBalancePreviousDay: "200", MarginPurchase: "40", MarginSales: "8", CashRedemption: "2", MarginPurchaseBalance: "230", ShortSaleBalancePreviousDay: "40", ShortSale: "8", ShortConvering: "2", StockRedemption: "1", ShortSaleBalance: "45" })));
  }
  if (url.includes("tpex_3insti_daily_trading")) {
    return json(otcSymbols.map((SecuritiesCompanyCode) => ({
      Date: "1150713",
      SecuritiesCompanyCode,
      "Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)-Difference": "300000",
      "SecuritiesInvestmentTrustCompanies-Difference": "100000",
      "Dealers-Difference": "-50000",
      TotalDifference: "350000",
    })));
  }
  if (url.includes("t187ap05_L")) {
    return json(listedSymbols.map((公司代號) => ({ 出表日期: "1150712", 資料年月: "11506", 公司代號, "營業收入-當月營收": "1000000", "營業收入-上月營收": "980000", "營業收入-去年當月營收": "870000", "累計營業收入-當月累計營收": "6000000", "累計營業收入-去年累計營收": "5450000", "營業收入-上月比較增減(%)": "2", "營業收入-去年同月增減(%)": "15", "累計營業收入-前期比較增減(%)": "10" })));
  }
  if (url.includes("mopsfin_t187ap05_O")) {
    return json(otcSymbols.map((公司代號) => ({ 出表日期: "1150713", 資料年月: "11506", 公司代號, "營業收入-當月營收": "500000", "營業收入-上月營收": "485000", "營業收入-去年當月營收": "416667", "累計營業收入-當月累計營收": "2900000", "累計營業收入-去年累計營收": "2589286", "營業收入-上月比較增減(%)": "3", "營業收入-去年同月增減(%)": "20", "累計營業收入-前期比較增減(%)": "12" })));
  }
  if (url.includes("t187ap06_L_ci")) {
    return json(listedSymbols.map((公司代號) => ({ 出表日期: "1150713", 年度: "115", 季別: "1", 公司代號, 營業收入: "1000", "營業毛利（毛損）": "400", "營業利益（損失）": "200", "本期淨利（淨損）": "150", "基本每股盈餘（元）": "2.5" })));
  }
  if (url.includes("t187ap07_L_ci")) {
    return json(listedSymbols.map((公司代號) => ({ 出表日期: "1150713", 年度: "115", 季別: "1", 公司代號, 資產總額: "1000", 負債總額: "400", 權益總額: "600" })));
  }
  if (url.includes("mopsfin_t187ap06_O_ci")) {
    return json(otcSymbols.map((SecuritiesCompanyCode) => ({ Date: "1150713", Year: "115", Season: "1", SecuritiesCompanyCode, 營業收入: "1000", "營業毛利（毛損）": "300", "營業利益（損失）": "100", "本期淨利（淨損）": "80", "基本每股盈餘（元）": "1.5" })));
  }
  if (url.includes("mopsfin_t187ap07_O_ci")) {
    return json(otcSymbols.map((SecuritiesCompanyCode) => ({ Date: "1150713", 年度: "115", 季別: "1", SecuritiesCompanyCode, 資產總計: "1000", 負債總計: "300", 權益總計: "700" })));
  }
  if (url.includes("lfkdkdyaatdlizryiyon.supabase.co/rest/v1/stock_price_history")) {
    return json(Array.from({ length: 130 }, (_, index) => ({
      trade_date: new Date(Date.UTC(2026, 0, 1 + index)).toISOString().slice(0, 10),
      open: 50 + index * 0.1,
      high: 51 + index * 0.1,
      low: 49 + index * 0.1,
      close: 50.5 + index * 0.1,
      volume: 600,
      trade_value: 30_000_000,
      transactions: 2_000,
    })).reverse());
  }
  if (/t187ap0[67]_[LO]_|mopsfin_t187ap0[67]_O_/.test(url)) return json([]);
  if (url.includes("supabase.co/functions/v1/twss-market-data")) {
    if (url.includes("type=stocks")) return json({ stocks: [], date: "2026-07-09" });
    return json({ fundamentals: [] });
  }
  return json({ error: "unmocked URL", url }, 404);
};

globalThis.fetch = fullFetch;

async function payload(path) {
  const response = await worker.fetch(new Request(`https://example.test${path}`), {}, {});
  assert.equal(response.ok, true, `${path} returned ${response.status}`);
  return response.json();
}

const health = await payload("/api/health");
assert.equal(health.version, "16.3");
assert.deepEqual(health.markets, ["上市股票", "上櫃股票", "ETF"]);

const stocks = await payload("/api/market-data?type=stocks&refresh=1");
assert.equal(stocks.stocks.length, 52);
assert.deepEqual(stocks.markets, { listed: 27, otc: 25, fallback: 0 });
assert.deepEqual(stocks.instruments, { listed: 25, otc: 25, etf: 2 });
assert.equal(stocks.mode, "live");
assert.equal(stocks.date, "2026-07-13");
assert.equal(stocks.dates.price.twse, "2026-07-13");
assert.equal(stocks.dates.price.tpex, "2026-07-13");
assert.equal(stocks.dates.margin.latest, "2026-07-09");

const listedStock = stocks.stocks.find((stock) => stock.symbol === "1101");
assert.equal(listedStock.close, 100);
assert.ok(listedStock.change < 0, "TWSE sign field should make the change negative");
assert.equal(listedStock.foreign, 200);
assert.equal(listedStock.trust, 50);
assert.equal(listedStock.dealer, -10);
assert.equal(listedStock.inst, 240);
assert.equal(listedStock.marginChange, 22);
assert.equal(listedStock.shortChange, 0);

const otcStock = stocks.stocks.find((stock) => stock.symbol === "4101");
assert.equal(otcStock.market, "上櫃");
assert.equal(otcStock.industry, "電腦及週邊設備業");
assert.equal(otcStock.pe, 12);
assert.equal(otcStock.foreign, 300);
assert.equal(otcStock.trust, 100);
assert.equal(otcStock.dealer, -50);
assert.equal(otcStock.inst, 350);
assert.equal(otcStock.marginChange, 30);
assert.equal(otcStock.shortChange, 5);

const etf = stocks.stocks.find((stock) => stock.symbol === "006208");
assert.equal(etf.instrumentType, "ETF");
assert.equal(etf.industry, "ETF");
assert.equal(etf.market, "上市");

const revenue = await payload("/api/market-data?type=revenue&refresh=1");
assert.equal(revenue.fundamentals.length, 50);
assert.equal(revenue.period, "2026-06");
assert.equal(revenue.publishedAt, "2026-07-13");
const otcRevenue = revenue.fundamentals.find((row) => row.symbol === "4101");
assert.equal(otcRevenue.rev, 20);
assert.equal(otcRevenue.revenuePreviousMonth, 485000000);
assert.equal(otcRevenue.revenueLastYearMonth, 416667000);
assert.equal(otcRevenue.revenueYtd, 2900000000);
assert.equal(otcRevenue.revenueLastYearYtd, 2589286000);
assert.equal(otcRevenue.revenueUnit, "TWD");
assert.equal(otcRevenue.revAcceleration, 8);
assert.equal(revenue.fundamentals.some((row) => row.symbol === "0050"), false);
assert.match(revenue.sourceStatus.fallback, /橫截面未列個股由後端逐檔/);

const financials = await payload("/api/market-data?type=financials&refresh=1");
assert.equal(financials.fundamentals.length, 50);
assert.equal(financials.period, "2026 Q1");
const listedFinancial = financials.fundamentals.find((row) => row.symbol === "1101");
assert.equal(listedFinancial.eps, 2.5);
assert.equal(listedFinancial.quarterRevenue, 1_000_000);
assert.equal(listedFinancial.quarterRevenueUnit, "TWD");
assert.equal(listedFinancial.grossMargin, 40);
assert.equal(listedFinancial.operatingMargin, 20);
assert.equal(listedFinancial.netMargin, 15);
assert.equal(listedFinancial.debt, 40);
assert.equal(listedFinancial.equityRatio, 60);
assert.equal(listedFinancial.roe, 100);
assert.equal(listedFinancial.roeEstimated, true);

const sources = await payload("/api/market-data?type=sources");
assert.equal(sources.sources.length, 6);
assert.equal(sources.auditedAt, "2026-07-14");

const otcHistory = await payload("/api/market-data?type=history&symbol=4101&market=上櫃&months=18&refresh=1");
assert.equal(otcHistory.market, "上櫃");
assert.equal(otcHistory.count, 130);
assert.equal(otcHistory.history.length, 130);
assert.match(otcHistory.source, /Supabase 後端歷史資料庫/);

const appResponse = await worker.fetch(new Request("https://example.test/app.js?v=16.3-ui3"), {}, {});
const appSource = await appResponse.text();
assert.match(appSource, /官方日期已核對/);
assert.match(appSource, /各資料來源日期/);
assert.match(appSource, /上市機會榜/);
assert.match(appSource, /上櫃機會榜/);
assert.match(appSource, /ETF 觀察榜/);
assert.match(appSource, /ETF 不適用/);
assert.match(appSource, /Promise\.allSettled/);
assert.match(appSource, /value\/1000000/);
assert.match(appSource, /market:stock\.market\|\|'上市'/);
assert.match(appSource, /每日深度快照/);
assert.match(appSource, /aria-label','關閉視窗/);
assert.match(appSource, /event\.key==='Escape'/);
assert.match(appSource, /sw\.js\?v=16\.3-ui3/);
assert.doesNotMatch(appSource, /廣告|促銷|VIP|贊助|免費試用|立即購買|解鎖/);
assert.doesNotMatch(appSource, /_\=\$\{Date\.now\(\)\}/);

const smartResponse = await worker.fetch(new Request("https://example.test/smart.js?v=16.3-ui3"), {}, {});
const smartSource = await smartResponse.text();
assert.match(smartSource, /機會股排行/);
assert.match(smartSource, /風險排除 → 成長確認 → 籌碼確認 → 價量進場判斷/);
assert.match(smartSource, /上市股提高外資/);
assert.match(smartSource, /上櫃股提高營收加速度/);
assert.match(smartSource, /ETF 不使用月營收、EPS、ROE/);
assert.match(smartSource, /資料信心低於 70% 不進正式榜/);
assert.match(smartSource, /近四季現金轉換/);
assert.match(smartSource, /最新月營收/);
assert.match(smartSource, /營收公布後反應：待滿 5 個交易日/);
assert.match(smartSource, /融資：不適用（不可融資）/);
assert.match(smartSource, /backtest\.json/);
assert.match(smartSource, /cache: 'no-store'/);
assert.match(smartSource, /globalThis\.twssUltimateSnapshot/);
assert.match(smartSource, /backend-rankings/);
assert.match(smartSource, /後端持續累積/);
assert.match(smartSource, /舊模型快照不作為 v16\.3 正式候選/);
assert.doesNotMatch(smartSource, /廣告|促銷|VIP|贊助|免費試用|立即購買|解鎖/);

const stylesResponse = await worker.fetch(new Request("https://example.test/styles.css?v=16.3-ui3"), {}, {});
const stylesSource = await stylesResponse.text();
assert.match(stylesSource, /min-width:48px/);
assert.match(stylesSource, /max-height:min\(76dvh,640px\)/);

const latestResponse = await worker.fetch(new Request("https://example.test/data/latest.json?v=16"), {}, {});
assert.equal(latestResponse.ok, true);
const latestSnapshot = await latestResponse.json();
assert.equal(latestSnapshot.version, "16.3");
assert.ok(latestSnapshot.groups.listed.length >= 1);
assert.ok(latestSnapshot.groups.otc.length >= 1);
assert.ok(latestSnapshot.groups.etf.length >= 1);

const { default: fallbackWorker } = await import("../worker/index.js?fallback-test");
globalThis.fetch = async (input) => {
  const url = String(input);
  if (url.includes("tpex.org.tw")) throw new Error("simulated TPEx outage");
  if (url.includes("supabase.co/functions/v1/twss-market-data") && url.includes("type=stocks")) {
    return json({
      date: "2026-07-13",
      stocks: otcSymbols.map((symbol, index) => ({ symbol, name: `上櫃備援${index + 1}`, market: "上櫃", industry: "未分類", close: 50 })),
    });
  }
  return fullFetch(input);
};

const fallbackResponse = await fallbackWorker.fetch(
  new Request("https://example.test/api/market-data?type=stocks&refresh=1"),
  {},
  {},
);
assert.equal(fallbackResponse.ok, true);
const fallbackStocks = await fallbackResponse.json();
assert.equal(fallbackStocks.mode, "partial");
assert.deepEqual(fallbackStocks.markets, { listed: 27, otc: 0, fallback: 25 });
assert.deepEqual(fallbackStocks.instruments, { listed: 25, otc: 25, etf: 2 });
assert.equal(fallbackStocks.stocks.length, 52);

console.log("Smoke tests passed: grouped stock/ETF ranking, revenue history fields, pacing, official fields, fallback, and UI labels");
