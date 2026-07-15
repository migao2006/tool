import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { handleMarketData } from "../src/market-data.js";
import { buildDeepData } from "../src/deep-data.js";
import { buildPeerContexts, scoreOpportunity } from "../src/opportunity-engine.js";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const companyLimit = Math.max(1, Number(process.env.SNAPSHOT_COMPANY_LIMIT || 10));
const etfLimit = Math.max(1, Number(process.env.SNAPSHOT_ETF_LIMIT || 10));

async function localPayload(type) {
  const url = new URL(`https://snapshot.local/api/market-data?type=${type}&refresh=1`);
  const response = await handleMarketData(new Request(url), url);
  const payload = await response.json();
  if (!response.ok) throw new Error(`${type}: ${payload.error || response.status}`);
  return payload;
}

function finite(value) {
  return value != null && Number.isFinite(Number(value));
}

function provisionalScore(stock, group) {
  const liquidity = Math.min(25, Math.max(0, Math.log10(Math.max(stock.value || 1, 1)) - 6) * 8);
  const valuation = stock.pe > 0 ? Math.max(0, 14 - stock.pe * 0.25) : 3;
  const chip = stock.inst == null || !stock.volume ? 0 : Math.max(-8, Math.min(12, stock.inst / stock.volume * 30));
  if (group === "etf") {
    return liquidity * 2 + Math.max(-10, Math.min(20, (stock.change || 0) * 3)) + Math.min(15, (stock.yield || 0) * 2);
  }
  const growth = finite(stock.rev) ? Math.max(-10, Math.min(35, stock.rev * 0.75 + 12)) : 0;
  const acceleration = finite(stock.revAcceleration) ? Math.max(-8, Math.min(18, stock.revAcceleration * 0.8)) : 0;
  const quality = finite(stock.roe) ? Math.max(-5, Math.min(18, stock.roe)) : finite(stock.eps) && stock.eps > 0 ? 7 : 0;
  return growth + acceleration + quality + valuation + chip + liquidity * (group === "otc" ? 0.8 : 0.55);
}

function groupOf(stock) {
  if (stock.instrumentType === "ETF" || /^00\d{2,4}[A-Z]?$/i.test(stock.symbol)) return "etf";
  return stock.market === "上櫃" ? "otc" : "listed";
}

function selectCandidates(stocks, group, limit) {
  const floors = group === "otc"
    ? { volume: 100, value: 10_000_000 }
    : group === "etf"
      ? { volume: 500, value: 20_000_000 }
      : { volume: 300, value: 20_000_000 };
  const ranked = stocks
    .filter((stock) => groupOf(stock) === group)
    .filter((stock) => !stock.hardExcluded)
    .filter((stock) => finite(stock.close) && finite(stock.volume) && stock.volume >= floors.volume)
    .filter((stock) => finite(stock.value) && stock.value >= floors.value)
    .map((stock) => ({ stock, score: provisionalScore(stock, group) }))
    .sort((a, b) => b.score - a.score);
  if (group === "etf") return ranked.slice(0, limit).map((entry) => entry.stock);
  const counts = new Map();
  const selected = [];
  for (const entry of ranked) {
    const count = counts.get(entry.stock.industry) || 0;
    if (count >= 2) continue;
    selected.push(entry.stock);
    counts.set(entry.stock.industry, count + 1);
    if (selected.length >= limit) break;
  }
  return selected;
}

function compactDeep(deep) {
  return {
    analysisVersion: deep.analysisVersion,
    symbol: deep.symbol,
    instrumentType: deep.instrumentType,
    market: deep.market,
    source: deep.source,
    fetchedAt: deep.fetchedAt,
    price: deep.price,
    priceHistory: deep.priceHistory?.slice(-180),
    revenue: deep.revenue,
    financial: deep.financial ? { ...deep.financial, history: undefined } : undefined,
    institutional: deep.institutional ? { ...deep.institutional, history: undefined } : undefined,
    margin: deep.margin ? { ...deep.margin, history: undefined } : undefined,
    lending: deep.lending,
    holdings: deep.holdings,
    etf: deep.etf,
    reused: deep.reused,
    missing: deep.missing,
  };
}

function compactStock(stock) {
  return {
    symbol: stock.symbol,
    name: stock.name,
    market: stock.market,
    instrumentType: stock.instrumentType,
    industry: stock.industry,
    open: stock.open,
    close: stock.close,
    high: stock.high,
    low: stock.low,
    change: stock.change,
    volume: stock.volume,
    value: stock.value,
    pe: stock.pe,
    pb: stock.pb,
    yield: stock.yield,
    rev: stock.rev,
    revMom: stock.revMom,
    revYtd: stock.revYtd,
    roe: stock.roe,
    eps: stock.eps,
    risk: stock.risk,
  };
}

async function analyzeGroup(group, selected, contexts, previousBySymbol, expectedPeriods) {
  const output = [];
  for (let index = 0; index < selected.length; index += 1) {
    const stock = selected[index];
    process.stdout.write(`[${group}] ${index + 1}/${selected.length} ${stock.symbol} ${stock.name}\n`);
    try {
      const deep = await buildDeepData(stock.symbol, stock.instrumentType, stock.market, {
        reuse: previousBySymbol.get(stock.symbol),
        expectedRevenuePeriod: expectedPeriods.revenue,
        expectedFinancialPeriod: expectedPeriods.financial,
      });
      const result = scoreOpportunity({
        stock,
        deep,
        risk: stock.risk || {},
        context: contexts[stock.symbol] || {},
      });
      output.push({ stock: compactStock(stock), analysis: compactDeep(deep), result });
    } catch (error) {
      output.push({
        stock: compactStock(stock),
        analysis: null,
        result: {
          symbol: stock.symbol,
          name: stock.name,
          group,
          score: null,
          confidence: 0,
          official: false,
          tier: "深度資料取得失敗",
          missing: [error instanceof Error ? error.message : "未知錯誤"],
          risk: { hardExcluded: false, hardReasons: [], deduction: 0, flags: [] },
          categories: [],
          reasons: [],
          archetypes: [],
        },
      });
    }
  }
  return output.sort((a, b) => (b.result.score ?? -1) - (a.result.score ?? -1));
}

async function writeJson(path, payload) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

const [stocksPayload, revenuePayload, financialPayload] = await Promise.all([
  localPayload("stocks"),
  localPayload("revenue"),
  localPayload("financials"),
]);

const merged = new Map(stocksPayload.stocks.map((stock) => [stock.symbol, { ...stock }]));
for (const row of [...(revenuePayload.fundamentals || []), ...(financialPayload.fundamentals || [])]) {
  if (merged.has(row.symbol)) Object.assign(merged.get(row.symbol), row);
}
const stocks = [...merged.values()];
const contexts = buildPeerContexts(stocks);
const selected = {
  listed: selectCandidates(stocks, "listed", companyLimit),
  otc: selectCandidates(stocks, "otc", companyLimit),
  etf: selectCandidates(stocks, "etf", etfLimit),
};

let previousSnapshot = null;
try {
  previousSnapshot = JSON.parse(await readFile(resolve(root, "public/data/latest.json"), "utf8"));
} catch {}
const previousBySymbol = new Map(
  Object.values(previousSnapshot?.groups || {}).flatMap((rows) => rows || [])
    .filter((row) => row?.stock?.symbol && row?.analysis)
    .map((row) => [row.stock.symbol, row.analysis]),
);
const expectedPeriods = {
  revenue: revenuePayload.period || null,
  financial: financialPayload.period || null,
};

const groups = {};
for (const group of ["listed", "otc", "etf"]) {
  groups[group] = await analyzeGroup(group, selected[group], contexts, previousBySymbol, expectedPeriods);
}

const generatedAt = new Date().toISOString();
let previousBacktest = null;
try {
  previousBacktest = JSON.parse(await readFile(resolve(root, "public/data/backtest.json"), "utf8"));
} catch {}

const snapshot = {
  version: "16.3",
  methodology: "persistent-batched-opportunity-engine-v16.3",
  generatedAt,
  dataDate: stocksPayload.date,
  sourceDates: {
    stocks: stocksPayload.dates,
    revenue: revenuePayload.dates,
    financials: financialPayload.dates,
  },
  universe: {
    counts: stocksPayload.instruments,
    verifiedCandidates: Object.fromEntries(Object.entries(groups).map(([key, rows]) => [key, rows.length])),
    formalCandidates: Object.fromEntries(Object.entries(groups).map(([key, rows]) => [key, rows.filter((row) => row.result.official).length])),
  },
  policy: {
    horizon: "1～8 週",
    confidenceFloor: 70,
    scoreWeights: { growth: 30, chip: 25, technical: 25, valuation: 10, market: 10 },
    maximumRiskDeduction: 30,
    separateGroups: true,
    missingDataRenormalized: true,
    noLookAhead: true,
  },
  groups,
  backtest: previousBacktest,
  disclaimer: "候選排序僅供研究，不構成投資建議、買賣邀約或獲利保證。",
};

// Archive by the market's actual trading date.  A weekend/holiday workflow run
// therefore refreshes the same last-trading-day file instead of creating fake
// "trading days" that would contaminate the 5/10/20-day backtest horizons.
const day = stocksPayload.date || generatedAt.slice(0, 10);
await writeJson(resolve(root, "public/data/latest.json"), snapshot);
const taipeiDay = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Taipei",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
}).format(new Date());
if (day === taipeiDay) {
  await writeJson(resolve(root, `data/snapshots/${day}.json`), {
    ...snapshot,
    capturedAt: generatedAt,
    marketPrices: stocks.map((stock) => ({
      symbol: stock.symbol,
      group: groupOf(stock),
      industry: stock.industry,
      open: stock.open,
      close: stock.close,
      high: stock.high,
      low: stock.low,
      change: stock.change,
    })),
    groups: Object.fromEntries(Object.entries(groups).map(([key, rows]) => [key, rows.map(({ stock, analysis, result }) => ({
      stock,
      analysis,
      result,
    }))])),
  });
} else {
  console.log(`Backtest archive skipped: market date ${day}, Taipei date ${taipeiDay}`);
}

console.log(`Snapshot ${day}: listed=${groups.listed.length}, otc=${groups.otc.length}, etf=${groups.etf.length}`);
