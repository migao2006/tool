import assert from "node:assert/strict";

const {
  buildDailyMarketReport,
  dailyMarketReportInternals,
  parseWatchlist,
  readDailyReport,
} = await import("../src/daily-market-report.js");
const dailyReportRoute = (await import("../api/v19/daily-report.js")).default;

const rows = [
  { symbol: "2330", name: "台積電", market: "上市", industry: "半導體業", change: 2.5, foreign: 1000, trust: 30, dealer: -10, inst: 1020 },
  { symbol: "2454", name: "聯發科", market: "上市", industry: "半導體業", change: 1.8, foreign: 300, trust: 50, dealer: 20, inst: 370 },
  { symbol: "3711", name: "日月光投控", market: "上市", industry: "半導體業", change: 1.2, foreign: 200, trust: 10, dealer: 0, inst: 210 },
  { symbol: "2303", name: "聯電", market: "上市", industry: "半導體業", change: -0.3, foreign: -100, trust: 0, dealer: 0, inst: -100 },
  { symbol: "2603", name: "長榮", market: "上市", industry: "航運業", change: -3.1, foreign: -600, trust: -30, dealer: -20, inst: -650 },
  { symbol: "2615", name: "萬海", market: "上市", industry: "航運業", change: -2.2, foreign: -200, trust: -20, dealer: -10, inst: -230 },
  { symbol: "2609", name: "陽明", market: "上市", industry: "航運業", change: 0.2, foreign: 10, trust: 0, dealer: 0, inst: 10 },
];

const ranking = {
  symbol: "2330",
  name: "台積電",
  market: "上市",
  industry: "半導體業",
  score: 91,
  confidence: 93,
  scoreDelta: 4,
  riskScore: 15,
  positiveReasons: ["營收成長", "法人買超"],
};
const home = {
  dataDate: "2026-07-15",
  groupDates: { listed: "2026-07-15" },
  groups: { listed: [ranking], otc: [], etf: [] },
  rankings: [ranking],
  todayPicks: [ranking],
  news: [{
    id: "news-1",
    title: "公司公布重要訊息",
    summary: "營運資訊更新。",
    source: "twse-mops",
    symbols: ["2330"],
    sentimentLabel: "benefit",
    publishedAt: "2026-07-15T08:00:00.000Z",
    url: "https://example.test/news-1",
  }],
  degraded: [],
};
const riskPage = { items: [{ ...ranking, symbol: "2603", name: "長榮", industry: "航運業", riskScore: 72 }] };
const groups = {
  listed: { date: "2026-07-15", stocks: rows },
  otc: { date: "2026-07-15", stocks: [] },
  etf: { date: "2026-07-15", stocks: [] },
};

assert.deepEqual(parseWatchlist(["2330, 2454", "bad", "2330"]), ["2330", "2454"]);
const longAnnouncement = "重大訊息內容".repeat(80);
const conciseAnnouncement = dailyMarketReportInternals.conciseNewsSummary(longAnnouncement);
assert.ok(conciseAnnouncement.length <= 161, "announcement summaries must stay compact for the first screen");
assert.match(conciseAnnouncement, /…$/);

const built = buildDailyMarketReport({
  home,
  marketGroups: groups,
  riskPage,
  watchlist: ["2330", "2603", "9999"],
  now: new Date("2026-07-15T10:00:00.000Z"),
});
assert.equal(built.reportVersion, "19.2-daily-report-v1");
assert.equal(built.dataDate, "2026-07-15");
assert.equal(built.generatedAt, "2026-07-15T10:00:00.000Z");
assert.equal(built.report.oneLine, built.report.todayInOneSentence);
assert.equal(built.report.marketStrength.sampleSize, rows.length);
assert.equal(built.report.hotIndustries[0].industry, "半導體業");
assert.equal(built.report.watchStocks[0].symbol, "2330");
assert.match(built.report.watchStocks[0].whyNotice, /營運數據有改善/);
assert.equal(built.report.risks, built.report.mainRisks);
assert.equal(built.report.news, built.report.importantNewsAndAnnouncements);
assert.equal(built.report.news[0].sentiment, "正面");
assert.equal(built.report.watchlistChanges[0].status, "AI 分數上升");
assert.equal(built.report.watchlistChanges[2].status, "資料更新中");
assert.match(built.beginnerNote, /不代表保證上漲或投資建議/);

dailyMarketReportInternals.clearCache();
let loadCount = 0;
const loaders = {
  home: async () => { loadCount += 1; return home; },
  market: async (group) => { loadCount += 1; return groups[group]; },
  risks: async () => { loadCount += 1; return riskPage; },
};
const first = await readDailyReport({ watchlist: ["2330"], loaders });
const second = await readDailyReport({ watchlist: ["2330"], loaders });
assert.equal(first.cache.status, "generated");
assert.equal(second.cache.status, "fresh");
assert.equal(loadCount, 5, "fresh cache must avoid repeated backend requests");

const optionsResponse = await dailyReportRoute.fetch(new Request("https://app.test/api/v19/daily-report", { method: "OPTIONS" }));
assert.equal(optionsResponse.status, 204);
const postResponse = await dailyReportRoute.fetch(new Request("https://app.test/api/v19/daily-report", { method: "POST" }));
assert.equal(postResponse.status, 405);

console.log("Daily market report tests passed: deterministic sections, concise news, novice explanations, watchlist changes, cache, and API guards");
