import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
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
  if (url.includes("supabase.co/rest/v1/rpc/twss_public_ranking_backtest")) {
    return json({
      version: "17.2", status: "insufficient_history", snapshotCount: 0, minimumSnapshots: 25,
      noLookAhead: true, byGroup: { listed: {}, otc: {}, etf: {} },
    });
  }
  if (url.includes("lfkdkdyaatdlizryiyon.supabase.co/rest/v1/stock_price_history")) {
    if (url.includes("symbol=eq.2454")) return json([]);
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
  if (url.includes("supabase.co/functions/v1/twss-sync-batch") && url.includes("mode=history")) {
    const symbol = new URL(url).searchParams.get("symbol");
    return json({
      mode: "live",
      symbol,
      source: symbol === "2454" ? "FinMind 按需補抓（已存入 Supabase）" : "Supabase 後端歷史資料庫",
      count: 130,
      period: "2026-05-10",
      history: Array.from({ length: 130 }, (_, index) => ({
        date: new Date(Date.UTC(2026, 0, 1 + index)).toISOString().slice(0, 10),
        open: 100 + index,
        high: 102 + index,
        low: 99 + index,
        close: 101 + index,
        volume: 1_000,
        value: 100_000_000,
        transactions: 3_000,
      })),
    });
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
assert.equal(health.version, "17.2");
assert.equal("aiResearch" in health, false);
assert.deepEqual(health.markets, ["上市股票", "上櫃股票", "ETF"]);

const dataHealthResponse = await worker.fetch(
  new Request("https://example.test/api/market-data?type=data-health&refresh=1"), {}, {},
);
assert.equal(dataHealthResponse.status, 400, "data-health must not be exposed by the public API");
const backendStatusResponse = await worker.fetch(
  new Request("https://example.test/api/market-data?type=backend-status&refresh=1"), {}, {},
);
assert.equal(backendStatusResponse.status, 400, "backend-status must not be exposed by the public API");

const rankingBacktest = await payload("/api/market-data?type=ranking-backtest&refresh=1");
assert.equal(rankingBacktest.status, "insufficient_history");
assert.equal(rankingBacktest.version, "17.2");
assert.equal(rankingBacktest.scoreModelVersion, "16.3");
assert.equal(rankingBacktest.noLookAhead, true);

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
assert.equal(sources.sources.some((source) => /gemini|ai/i.test(`${source.id} ${source.name}`)), false);

const otcHistory = await payload("/api/market-data?type=history&symbol=4101&market=上櫃&months=18&refresh=1");
assert.equal(otcHistory.market, "上櫃");
assert.equal(otcHistory.count, 130);
assert.equal(otcHistory.history.length, 130);
assert.match(otcHistory.source, /Supabase 後端歷史資料庫/);

const onDemandHistory = await payload("/api/market-data?type=history&symbol=2454&market=上市&months=18&refresh=1");
assert.equal(onDemandHistory.market, "上市");
assert.equal(onDemandHistory.count, 130);
assert.equal(onDemandHistory.history.length, 130);
assert.match(onDemandHistory.source, /按需補抓/);

const removedResearchResponse = await worker.fetch(new Request("https://example.test/api/ai-research"), {}, {});
assert.equal(removedResearchResponse.status, 404);

const pageResponse = await worker.fetch(new Request("https://example.test/"), {}, {});
const pageSource = await pageResponse.text();
const contentSecurityPolicy = pageResponse.headers.get("content-security-policy") || "";
assert.match(contentSecurityPolicy, /https:\/\/gxwrczuwshndnjactrij\.supabase\.co/,
  "the browser policy must allow the CORE project");
assert.match(contentSecurityPolicy, /https:\/\/lfkdkdyaatdlizryiyon\.supabase\.co/,
  "the shared policy must continue allowing the standalone MARKET administrator console");
assert.doesNotMatch(pageSource, /id="adminBtn"/,
  "the CORE-authenticated main application must not embed a MARKET administrator entry");
assert.match(pageSource, /app\.js\?v=19\.2\.0/);
const publicPageSource = await readFile(new URL("../public/index.html", import.meta.url), "utf8");
const publicAppSource = await readFile(new URL("../public/app.js", import.meta.url), "utf8");
const publicSmartSource = await readFile(new URL("../public/smart.js", import.meta.url), "utf8");
const publicStylesSource = await readFile(new URL("../public/styles.css", import.meta.url), "utf8");
assert.match(publicPageSource, /app\.js\?v=19\.2\.0/);
assert.doesNotMatch(publicPageSource, /id="themeToggle"|data-tab="(?:forecast|verify)"/);
const adminPageSource = await readFile(new URL("../public/admin.html", import.meta.url), "utf8");
const adminScriptSource = await readFile(new URL("../public/admin.js", import.meta.url), "utf8");
assert.match(adminPageSource, /icon\.svg\?v=19\.2\.0/);
assert.match(adminPageSource, /styles\.css\?v=19\.2\.0/);
assert.match(adminPageSource, /admin\.js\?v=19\.2\.0/);
assert.match(adminScriptSource, /https:\/\/lfkdkdyaatdlizryiyon\.supabase\.co/,
  "the standalone administrator console must remain on MARKET");
assert.match(adminScriptSource, /twss-market-admin-session-v18/,
  "the MARKET administrator must use an isolated session key");
assert.doesNotMatch(adminScriptSource, /gxwrczuwshndnjactrij|twss-core-session/,
  "the standalone MARKET console must never load the CORE session");

const appResponse = await worker.fetch(new Request("https://example.test/app.js?v=18.0.0"), {}, {});
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
assert.doesNotMatch(appSource, /snapshotHistory/, "the removed compact snapshot must not be downloaded as a history fallback");
assert.match(appSource, /body\?\.error\|\|`HTTP \$\{r\.status\}`/, "the UI must preserve structured API errors");
assert.match(appSource, /交易日不足 60 日/, "partial histories must not be presented as complete technical data");
assert.match(appSource, /120000,0/, "opening one detail must not automatically consume a second repair attempt");
assert.match(appSource, /aria-label','關閉視窗/);
assert.match(appSource, /event\.key==='Escape'/);
assert.match(appSource, /sw\.js\?v=19\.2\.0/);
assert.match(appSource, /timeZone:TAIPEI_TIME_ZONE/,
  "local date defaults must use Asia/Taipei");
assert.match(appSource, /history\.scrollRestoration='manual'/,
  "Safari and installed PWAs must not restore an obsolete home-page scroll offset");
assert.match(appSource, /S\.tab==='home'&&\(event\.persisted\|\|initialHomeScrollPending\)/,
  "bfcache restoration must not discard the user's scroll position on non-home tabs");
assert.match(appSource, /function resetPageScroll[\s\S]*window\.scrollTo\(0,0\)[\s\S]*document\.documentElement\.scrollTop=0[\s\S]*document\.body\.scrollTop=0/,
  "scroll reset must cover the iOS document and body scrolling implementations");
assert.match(appSource, /readMarketBootCache\(\)[\s\S]*loadLatestSnapshot\(\)[\s\S]*fetchJson\(`\$\{EDGE\}\?type=stocks`/,
  "the first paint must use local or static data before the live stocks API completes");
assert.match(appSource, /settleInitialHomeScroll\(\)[\s\S]*loadFundamentals\(\)/,
  "the first complete market render must settle at the top before asynchronous enrichment");
assert.match(appSource, /navigateToTab[\s\S]*resetPageScroll\(\)/,
  "opening a different page must not inherit the previous page scroll offset");
assert.match(appSource, /CORE_SUPABASE_URL='https:\/\/gxwrczuwshndnjactrij\.supabase\.co'/,
  "the main application must use CORE for Auth and per-user data");
assert.match(appSource, /CORE_SESSION_KEY='twss-core-session-v18'/,
  "the main application must isolate its CORE session");
assert.doesNotMatch(appSource, /https:\/\/lfkdkdyaatdlizryiyon\.supabase\.co/,
  "the main application must not have a direct MARKET destination for its CORE JWT");
assert.match(appSource, /function userDataKey\(kind,userId=sessionUserId\(\)\)/,
  "local user data must be partitioned by the authenticated CORE user id");
assert.doesNotMatch(appSource, /prediction_logs|getPredictions|setPredictions|upsertPrediction|recordPrediction|data-verify-stock|未來漲跌預測|預測驗證/,
  "the removed prediction UI must not retain active prediction data or controls");
assert.match(appSource, /watchlist_groups[\s\S]*watchlist_items/,
  "the implemented watchlist must sync through CORE");
assert.doesNotMatch(appSource, /investment_journal|saveJournal|deleteJournal|getJournal|setJournal|openJournalModal|journalSection|data-(?:patch-)?journal|data-journal-stock|投資紀錄|買入紀錄|賣出紀錄/i,
  "v19 must not expose or synchronize personal investment records");
assert.match(appSource, /function navigateToTab\(tab\)\{if\(!\['home','opportunities','mine'\]\.includes\(tab\)\)return/,
  "direct navigation must only allow the three retained public pages");
assert.match(appSource, /\/auth\/v1\/logout/,
  "logout must revoke the CORE Supabase session before clearing it locally");
assert.match(adminScriptSource, /twss_admin_operations_log/);
assert.doesNotMatch(appSource, /SUPABASE_(?:SERVICE_ROLE|SECRET)_KEY|sb_secret_/,
  "administrator UI source must never contain a server secret");
assert.doesNotMatch(appSource, /資料健康中心|data-health|loadDataHealth|openDataHealth|statusCard|refreshDataHealth/,
  "the public application must not load or render administrator diagnostics");
assert.doesNotMatch(appSource, /gemini|ai[-_ ]?research|AI 研究|AI 摘要|data-ai/i,
  "paid research UI and endpoints must be fully removed");
assert.doesNotMatch(appSource, /廣告|促銷|VIP|贊助|免費試用|立即購買|解鎖/);
assert.doesNotMatch(appSource, /_\=\$\{Date\.now\(\)\}/);

const patchResponse = await worker.fetch(new Request("https://example.test/patch.js?v=18.0.0"), {}, {});
const patchSource = await patchResponse.text();
assert.match(patchSource, /候選比較/);
assert.match(patchSource, /同一組最多比較 4 檔/);
assert.match(patchSource, /不同市場不放在同一張表/);
assert.match(patchSource, /text\/csv;charset=utf-8/);
assert.match(patchSource, /匯出上市 CSV/);
assert.match(patchSource, /匯出上櫃 CSV/);
assert.match(patchSource, /匯出 ETF CSV/);
assert.match(patchSource, /正式排名累積中/);
assert.match(patchSource, /自選清單/);
assert.match(patchSource, /規則提醒/);
assert.doesNotMatch(patchSource, /saveJournal|deleteJournal|getJournal|openJournalModal|journalSection|data-(?:patch-)?journal|data-journal-stock|投資紀錄|買入紀錄|賣出紀錄/i,
  "the active mine-page override must not restore the removed investment journal");
assert.doesNotMatch(patchSource, /recordPrediction|evaluatePredictions|runTechnicalBacktest|data-verify-stock|未來漲跌預測|預測驗證|預測紀錄/,
  "the comparison override must not restore removed prediction features");
assert.doesNotMatch(patchSource, /gemini|ai[-_ ]?research|AI 研究|AI 摘要|data-ai/i,
  "paid research UI and endpoints must remain removed from the comparison release");

const smartResponse = await worker.fetch(new Request("https://example.test/smart.js?v=18.0.0"), {}, {});
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
assert.doesNotMatch(smartSource, /backtest\.json|runTechnicalBacktest|data-verify-stock/,
  "the v19 ranking override must not load or expose future-price backtests");
assert.match(smartSource, /cache: 'no-store'/);
assert.match(smartSource, /globalThis\.twssUltimateSnapshot/);
assert.match(smartSource, /backend-rankings/);
assert.match(smartSource, /後端持續累積/);
assert.match(smartSource, /analysisVersion === EXPECTED_ANALYSIS_VERSION/,
  "only snapshots from the expected analysis model may become formal candidates");
assert.doesNotMatch(smartSource, /資料健康中心|data-health|statusCard/,
  "the ranking override must not restore the removed health-center entry");
assert.doesNotMatch(smartSource, /廣告|促銷|VIP|贊助|免費試用|立即購買|解鎖/);
for (const heading of ['今日市場摘要', '今日 AI 精選', '分數上升最快', 'AI 排行榜', '自選股重要變化', '今日重要新聞與公告']) {
  assert.match(publicSmartSource, new RegExp(heading), `v19 home must include ${heading}`);
}
for (const marketName of ['加權指數', '櫃買指數', '台指期']) {
  assert.match(publicSmartSource, new RegExp(marketName), `v19 market strip must include ${marketName}`);
}
assert.match(publicSmartSource, /\/api\/market-data\?type=benchmarks/);
assert.match(publicSmartSource, /v19-index-strip/);
assert.match(publicSmartSource, /v19-featured/);
assert.match(publicSmartSource, /v19-compact-row/);
assert.match(publicSmartSource, /\/api\/v19/);
assert.match(publicSmartSource, /optionalJson\('\/home'\)/);
assert.match(publicSmartSource, /optionalJson\(rankingQuery\(10\)\)/);
assert.match(publicSmartSource, /twssLatestSnapshotPromise/,
  "the verified static snapshot must paint before background APIs finish");
assert.match(publicSmartSource, /rankingQuery\(20, v19\.rankingNextCursor\)/);
assert.match(publicSmartSource, /payload\.nextCursor/);
assert.match(publicSmartSource, /params\.set\('cursor', cursor\)/);
assert.doesNotMatch(publicSmartSource, /rankings\?limit=100/);
assert.match(publicSmartSource, /sort: v19\.sort/);
assert.match(publicSmartSource, /if \(v19\.rankings\) return allRows\(\)/,
  "successful server pagination must not be mixed with unseen local ranking rows");
assert.match(publicSmartSource, /risk_asc/);
assert.match(publicSmartSource, /risk_desc/);
assert.doesNotMatch(publicSmartSource, /value="(?:turnover_desc|name_asc)"/);
assert.match(publicSmartSource, /optionalJson\(`\/stocks\?symbol=\$\{encodeURIComponent\(symbol\)\}`\)/);
assert.match(publicSmartSource, /visible: 10/);
assert.match(publicSmartSource, /v19\.visible \+= 20/);
assert.match(publicSmartSource, /輸入代號或名稱/);
assert.match(publicSmartSource, /對立訊號/);
assert.match(publicSmartSource, /分數歷史/);
assert.match(publicSmartSource, /const tradeDate = dateOnly\(first\(raw\.tradeDate, raw\.trade_date/);
assert.match(publicSmartSource, /行情日 \$\{esc\(row\.tradeDate \|\| '待確認'\)\}/);
assert.match(publicSmartSource, /分析日 \$\{esc\(row\.analysisDataDate \|\| '待確認'\)\}/);
assert.doesNotMatch(publicSmartSource, /行情日 \$\{esc\(row\.dataDate \|\| S\.date/,
  "analysis dates must never be presented as quote dates");
assert.match(publicSmartSource, /同產業參考（非 AI 關聯判定）/);
assert.match(publicSmartSource, /資料不足，尚無可驗證的推薦原因/);
assert.match(publicSmartSource, /Array\.isArray\(value\) \? value\.length > 0 : Boolean\(value\)/,
  "an empty degraded array must not mark the v19 API as degraded");
assert.match(publicSmartSource, /degraded: hasDegradation\(/,
  "an empty degraded array must not mark a stock detail as degraded");
assert.match(publicSmartSource, /watchRows: \[\]/);
assert.match(publicSmartSource, /watchFingerprint: null/);
assert.match(publicSmartSource, /fingerprint === v19\.watchFingerprint/);
assert.match(publicSmartSource, /loadWatchRows\(\);\r?\n\s*\};/,
  "render binding must refresh watch details only when the watchlist fingerprint changes");
assert.match(publicSmartSource, /slice\(0, 20\)/);
assert.match(publicSmartSource, /index \+= 4/);
assert.match(publicSmartSource, /Promise\.allSettled\(batch\)/);
assert.match(publicSmartSource, /v19\.watchRows\.forEach/);
assert.match(publicSmartSource, /function homeGroupRows\(\)/);
assert.match(publicSmartSource, /v19\.home\?\.groups\?\.\[key\]/);
assert.match(publicSmartSource, /分析結果已可使用/,
  "usable provisional rankings must not look indefinitely blocked");
assert.match(publicSmartSource, /背景持續補齊/,
  "partial analysis must clearly state that background work continues");
assert.match(publicSmartSource, /deep_listed: '上市'/,
  "the public status must include per-market progress");
assert.doesNotMatch(publicSmartSource, /SUPABASE_(?:SERVICE_ROLE|SECRET)_KEY|sb_secret_/);
assert.doesNotMatch(publicSmartSource, /data-tab="admin"|id="adminBtn"/);
assert.match(publicSmartSource, /optionalJson\(`\/daily-report/);
assert.match(publicSmartSource, /\/data\/daily-report\.json/);
assert.match(publicSmartSource, /watchlist\.join\(','\)/,
  "the dynamic daily report must include the current watchlist without blocking first paint");
assert.match(publicSmartSource, /item\.whyNotice/,
  "beginner-friendly stock reasons from the report API must be preserved");
assert.match(publicSmartSource, /raw\.watchlistChanges/,
  "the daily report must render watchlist changes when available");
assert.match(publicSmartSource, /id="v19NewsMore"/);
assert.match(publicSmartSource, /三分鐘看懂/);
assert.doesNotMatch(publicSmartSource, /查看既有預測驗證/);
assert.match(publicAppSource, /sw\.js\?v=19\.2\.0/);

const stylesResponse = await worker.fetch(new Request("https://example.test/styles.css?v=18.0.0"), {}, {});
const stylesSource = await stylesResponse.text();
assert.match(stylesSource, /min-width:48px/);
assert.match(stylesSource, /max-height:min\(76dvh,640px\)/);
assert.match(stylesSource, /compare-table-wrap/);
assert.match(stylesSource, /compare-export-grid/);
assert.match(stylesSource, /authenticated administrator operations console/);
assert.match(stylesSource, /\.app-shell\{overflow-anchor:none\}/,
  "asynchronous home renders must not let Safari move the viewport anchor");
assert.doesNotMatch(stylesSource, /\.ai-(?:card|panel|action|summary|scenario)/);
assert.doesNotMatch(publicStylesSource, /data-theme="light"|prefers-color-scheme:light|\.theme-toggle/);
assert.match(publicStylesSource, /\.v19-ranking-filter/);
assert.match(publicStylesSource, /\.v19-index-strip/);
assert.match(publicStylesSource, /\.v19-featured/);
assert.match(publicStylesSource, /\.v19-compact-row/);

const latestResponse = await worker.fetch(new Request("https://example.test/data/latest.json?v=16"), {}, {});
assert.equal(latestResponse.ok, true);
const latestSnapshot = await latestResponse.json();
assert.equal(latestSnapshot.version, "16.3");
assert.equal("sync" in (latestSnapshot.backend || {}), false,
  "the public fallback snapshot must not contain administrator synchronization state");
assert.doesNotMatch(JSON.stringify(latestSnapshot.backend || {}),
  /last_error|lease_owner|lease_until|finmindBudget|reservationId|repair_reasons/i,
  "the public fallback snapshot must not retain internal error, lease, quota, or repair fields");
assert.ok(latestSnapshot.groups.listed.length >= 1);
assert.ok(latestSnapshot.groups.otc.length >= 1);
assert.ok(latestSnapshot.groups.etf.length >= 1);

const dailyReportResponse = await worker.fetch(new Request("https://example.test/data/daily-report.json"), {}, {});
assert.equal(dailyReportResponse.ok, true);
const dailyReport = await dailyReportResponse.json();
assert.match(dailyReport.reportVersion, /^19\.2-/);
assert.ok(dailyReport.report?.oneLine);
assert.ok(Array.isArray(dailyReport.report?.news));

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
