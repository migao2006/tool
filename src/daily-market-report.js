import { readBackendMarketStocks } from "./backend-store.js";
import { readV19Home, readV19Rankings } from "./v19-backend.js";

const REPORT_VERSION = "19.2-daily-report-v1";
const FRESH_TTL_MS = 15 * 60 * 1_000;
const STALE_TTL_MS = 24 * 60 * 60 * 1_000;
const MAX_WATCHLIST = 30;
const cache = new Map();

const finite = (value) => value != null && Number.isFinite(Number(value));
const number = (value) => finite(value) ? Number(value) : null;
const clamp = (value, min = 0, max = 100) => Math.max(min, Math.min(max, Number(value)));
const round = (value, digits = 2) => finite(value) ? Number(Number(value).toFixed(digits)) : null;
const average = (values) => {
  const valid = values.filter(finite).map(Number);
  return valid.length ? valid.reduce((sum, value) => sum + value, 0) / valid.length : null;
};
const sum = (values) => values.filter(finite).reduce((total, value) => total + Number(value), 0);
const isoDate = (value) => /^\d{4}-\d{2}-\d{2}/.test(String(value || ""))
  ? String(value).slice(0, 10)
  : null;
const unique = (values) => [...new Set(values.filter(Boolean))];

export function parseWatchlist(input) {
  const values = Array.isArray(input) ? input : String(input || "").split(",");
  return unique(values
    .flatMap((value) => String(value || "").split(","))
    .map((value) => value.trim().toUpperCase())
    .filter((value) => /^[0-9]{4,6}[A-Z]?$/.test(value)))
    .slice(0, MAX_WATCHLIST);
}

function marketRows(groups = {}) {
  return ["listed", "otc", "etf"].flatMap((group) =>
    Array.isArray(groups[group]?.stocks) ? groups[group].stocks : []);
}

function marketBreadth(rows) {
  const tradable = rows.filter((row) =>
    row.instrumentType !== "ETF" && String(row.industry || "").toUpperCase() !== "ETF" && finite(row.change));
  const up = tradable.filter((row) => Number(row.change) > 0).length;
  const down = tradable.filter((row) => Number(row.change) < 0).length;
  const flat = Math.max(0, tradable.length - up - down);
  const breadthPct = tradable.length ? up / tradable.length * 100 : null;
  const averageChangePct = average(tradable.map((row) => row.change));
  const changeScore = averageChangePct == null ? 50 : clamp(50 + averageChangePct * 15);
  const strengthScore = breadthPct == null
    ? changeScore
    : clamp(breadthPct * 0.55 + changeScore * 0.45);
  const level = strengthScore >= 65 ? "偏強"
    : strengthScore <= 35 ? "偏弱"
      : "震盪";
  const explanation = tradable.length
    ? `全市場有 ${up} 檔上漲、${down} 檔下跌，平均漲跌 ${averageChangePct >= 0 ? "+" : ""}${round(averageChangePct)}%。${level === "偏強" ? "買盤較有優勢，但仍要避開短線漲幅過大的股票。" : level === "偏弱" ? "賣壓較明顯，選股宜保守並控制風險。" : "多空力量接近，適合逐檔確認基本面與風險。"}`
    : "市場快照尚未完整，先使用最近一次分析結果，稍後會背景更新。";
  return {
    level,
    score: round(strengthScore, 1),
    up,
    down,
    flat,
    breadthPct: round(breadthPct, 1),
    averageChangePct: round(averageChangePct),
    sampleSize: tradable.length,
    explanation,
  };
}

function industryAnalysis(rows) {
  const buckets = new Map();
  for (const row of rows) {
    const industry = String(row.industry || "").trim();
    if (!industry || industry === "未分類" || industry.toUpperCase() === "ETF") continue;
    if (!buckets.has(industry)) buckets.set(industry, []);
    buckets.get(industry).push(row);
  }
  return [...buckets.entries()].map(([industry, stocks]) => {
    const changes = stocks.map((row) => row.change).filter(finite).map(Number);
    const up = changes.filter((value) => value > 0).length;
    const averageChangePct = average(changes);
    const breadthPct = changes.length ? up / changes.length * 100 : null;
    const momentum = (averageChangePct ?? 0) + (breadthPct == null ? 0 : (breadthPct - 50) / 25);
    const representatives = [...stocks]
      .filter((row) => finite(row.change))
      .sort((left, right) => Number(right.change) - Number(left.change))
      .slice(0, 3)
      .map((row) => ({ symbol: row.symbol, name: row.name || row.symbol, changePct: round(row.change) }));
    return {
      industry,
      stockCount: stocks.length,
      averageChangePct: round(averageChangePct),
      breadthPct: round(breadthPct, 1),
      representatives,
      momentum,
      explanation: averageChangePct == null
        ? `${industry}資料仍在更新，暫不判斷強弱。`
        : `${industry}平均${averageChangePct >= 0 ? "上漲" : "下跌"}${Math.abs(round(averageChangePct))}%，${breadthPct >= 60 ? "多數股票同步走強" : breadthPct <= 40 ? "只有少數股票上漲" : "個股表現分歧"}。`,
    };
  }).filter((item) => item.stockCount >= 3 && item.averageChangePct != null)
    .sort((left, right) => right.momentum - left.momentum)
    .slice(0, 5)
    .map(({ momentum, ...item }) => item);
}

function institutionalDirection(rows) {
  const foreign = sum(rows.map((row) => row.foreign));
  const trust = sum(rows.map((row) => row.trust));
  const dealer = sum(rows.map((row) => row.dealer));
  const total = rows.some((row) => finite(row.inst))
    ? sum(rows.map((row) => row.inst))
    : foreign + trust + dealer;
  const sampleSize = rows.filter((row) =>
    finite(row.inst) || finite(row.foreign) || finite(row.trust) || finite(row.dealer)).length;
  const direction = !sampleSize ? "資料更新中" : total > 0 ? "偏買方" : total < 0 ? "偏賣方" : "中性";
  return {
    direction,
    total: round(total, 0),
    foreign: round(foreign, 0),
    trust: round(trust, 0),
    dealer: round(dealer, 0),
    sampleSize,
    explanation: !sampleSize
      ? "法人資料尚未完整，暫時不做方向判斷。"
      : `三大法人合計為${total > 0 ? "買超" : total < 0 ? "賣超" : "買賣相當"}${Math.abs(round(total, 0)).toLocaleString("zh-TW")} 張；這代表短線資金態度，不等於股價一定會同方向變動。`,
  };
}

function noviceReason(reasons, fallback) {
  const text = (Array.isArray(reasons) ? reasons : []).join(" ");
  if (/營收|獲利|毛利|現金流|基本面/.test(text)) return "最近公布的營運數據有改善，基本面值得繼續追蹤。";
  if (/法人|外資|投信|籌碼/.test(text)) return "外資、投信或自營商的買盤較積極，市場資金正在關注。";
  if (/均線|趨勢|突破|動能|量價|成交量/.test(text)) return "近期股價與成交量表現較強，市場買盤比先前積極。";
  if (/殖利率|股利|估值|本益比/.test(text)) return "目前價格相對營運或配息條件具有吸引力，但仍要確認能否持續。";
  return fallback;
}

function noviceRisk(item, marketRow = {}) {
  const reasons = Array.isArray(item?.riskReasons) ? item.riskReasons.join(" ") : "";
  if (marketRow.full || /全額交割/.test(reasons)) return "交易限制較高，流動性與公司風險都要特別留意。";
  if (marketRow.disp || /處置/.test(reasons)) return "目前可能有交易處置措施，成交方式與流動性可能受影響。";
  if (finite(marketRow.change) && Number(marketRow.change) >= 6) return "短線已明顯上漲，追高時容易遇到價格快速回落。";
  if (finite(marketRow.change) && Number(marketRow.change) <= -4) return "今日跌幅較大，應先確認是否有基本面或消息面的負面變化。";
  if (finite(item?.riskScore) && Number(item.riskScore) >= 60) return "風險分數偏高，波動或資料訊號有較多不利因素。";
  return "分析分數可能隨新資料更新，仍需分散風險並自行判斷。";
}

function stockProjection(item, stockMap, kind = "opportunity") {
  const marketRow = stockMap.get(String(item?.symbol || "")) || {};
  const score = number(item?.aiScore?.value ?? item?.score);
  const reason = noviceReason(
    item?.positiveReasons,
    kind === "risk"
      ? "目前不利訊號較多，先觀察風險是否改善。"
      : "AI 綜合分數位於市場前段，值得列入研究清單。",
  );
  return {
    symbol: String(item?.symbol || marketRow.symbol || ""),
    name: item?.name || marketRow.name || item?.symbol || "",
    market: item?.market || marketRow.market || null,
    industry: item?.industry || marketRow.industry || null,
    aiScore: score,
    confidence: number(item?.confidence ?? item?.aiScore?.confidence),
    changePct: round(marketRow.change),
    riskScore: number(item?.riskScore),
    whyNotice: reason,
    advantage: reason,
    risk: noviceRisk(item, marketRow),
  };
}

function importantNews(items = []) {
  return items.slice(0, 8).map((item) => {
    const sentiment = item.sentimentLabel === "benefit" ? "正面"
      : item.sentimentLabel === "risk" ? "負面"
        : "中性";
    return {
      id: item.id || null,
      title: item.title || "未命名公告",
      summary: item.summary || "請開啟原始連結確認完整內容。",
      source: item.source || null,
      category: item.category || null,
      symbols: Array.isArray(item.symbols) ? item.symbols : [],
      publishedAt: item.publishedAt || item.eventDate || null,
      url: item.url || null,
      impact: sentiment === "正面"
        ? "內容偏正面，但仍要觀察是否已反映在股價。"
        : sentiment === "負面"
          ? "內容可能增加營運或股價風險，需優先確認細節。"
          : "目前無法只靠標題判定影響，建議閱讀公告原文。",
      sentiment,
    };
  });
}

function watchlistChanges(symbols, stockMap, rankingMap) {
  return symbols.map((symbol) => {
    const stock = stockMap.get(symbol);
    const ranking = rankingMap.get(symbol);
    if (!stock && !ranking) {
      return {
        symbol,
        status: "資料更新中",
        explanation: "目前快照尚未找到這檔股票，系統會在背景更新。",
      };
    }
    const change = number(stock?.change);
    const scoreDelta = number(ranking?.scoreDelta);
    const status = scoreDelta >= 3 ? "AI 分數上升"
      : scoreDelta <= -3 ? "AI 分數下降"
        : change >= 2 ? "今日明顯上漲"
          : change <= -2 ? "今日明顯下跌"
            : "沒有重大變化";
    const details = [];
    if (change != null) details.push(`股價${change >= 0 ? "上漲" : "下跌"}${Math.abs(round(change))}%`);
    if (scoreDelta != null) details.push(`AI 分數變化 ${scoreDelta >= 0 ? "+" : ""}${round(scoreDelta, 1)}`);
    return {
      symbol,
      name: ranking?.name || stock?.name || symbol,
      status,
      changePct: round(change),
      scoreDelta: round(scoreDelta, 1),
      explanation: details.length ? `${details.join("；")}。這是提醒，不代表買賣建議。` : "目前沒有足夠資料判斷重大變化。",
    };
  });
}

function riskThemes(rows, riskStocks, breadth) {
  const items = [];
  if (breadth.level === "偏弱") {
    items.push({
      title: "市場賣壓偏高",
      explanation: "下跌股票較多，個股容易受到大盤拖累，宜降低追高與集中持股風險。",
    });
  }
  const volatile = rows.filter((row) =>
    row.instrumentType !== "ETF" && finite(row.change) && Math.abs(Number(row.change)) >= 6).length;
  if (volatile) {
    items.push({
      title: "短線波動放大",
      explanation: `共有 ${volatile} 檔股票單日漲跌超過 6%，追價前應先確認成交量與消息來源。`,
    });
  }
  if (riskStocks.some((item) => finite(item.riskScore) && Number(item.riskScore) >= 60)) {
    items.push({
      title: "部分高分股仍有風險訊號",
      explanation: "AI 分數高不代表沒有風險，請同時閱讀每檔股票的風險說明。",
    });
  }
  if (!items.length) {
    items.push({
      title: "留意資料與突發消息",
      explanation: "盤後資料不是即時報價，重大消息可能在分析完成後才發生。",
    });
  }
  return items.slice(0, 4);
}

export function buildDailyMarketReport({ home = {}, marketGroups = {}, riskPage = {}, watchlist = [], now = new Date() } = {}) {
  const rows = marketRows(marketGroups);
  const stockMap = new Map(rows.map((row) => [String(row.symbol || ""), row]));
  const rankingRows = unique([
    ...(Array.isArray(home.rankings) ? home.rankings : []),
    ...Object.values(home.groups || {}).flatMap((items) => Array.isArray(items) ? items : []),
  ].map((item) => item?.symbol)).map((symbol) => {
    const all = [
      ...(Array.isArray(home.rankings) ? home.rankings : []),
      ...Object.values(home.groups || {}).flatMap((items) => Array.isArray(items) ? items : []),
    ];
    return all.find((item) => item?.symbol === symbol);
  }).filter(Boolean);
  const rankingMap = new Map(rankingRows.map((row) => [String(row.symbol || ""), row]));
  const breadth = marketBreadth(rows);
  const hotIndustries = industryAnalysis(rows);
  const institutions = institutionalDirection(rows);
  const opportunityStocks = (home.todayPicks || home.rankings || [])
    .slice(0, 6)
    .map((item) => stockProjection(item, stockMap));
  const riskStocks = (riskPage.items || [])
    .slice(0, 6)
    .map((item) => stockProjection(item, stockMap, "risk"));
  const news = importantNews(home.news || []);
  const headline = `${breadth.level === "偏強" ? "市場買盤較有優勢" : breadth.level === "偏弱" ? "市場賣壓較明顯" : "市場多空拉鋸"}${hotIndustries[0] ? `，${hotIndustries[0].industry}相對活躍` : ""}。`;
  const marketDates = Object.fromEntries(["listed", "otc", "etf"].map((group) => [
    group,
    isoDate(marketGroups[group]?.date),
  ]));
  const distinctMarketDates = unique(Object.values(marketDates)).sort();
  const marketDatesAligned = distinctMarketDates.length <= 1;
  const dates = unique([
    home.dataDate,
    ...Object.values(home.groupDates || {}),
    ...Object.values(marketGroups).map((group) => group?.date),
  ].map(isoDate)).sort();
  const degraded = unique([
    ...(Array.isArray(home.degraded) ? home.degraded : []),
    ...(rows.length ? [] : ["market_snapshot_unavailable"]),
    ...(marketDatesAligned ? [] : ["market_dates_misaligned"]),
    ...((riskPage.items || []).length ? [] : ["risk_ranking_unavailable"]),
    ...((home.news || []).length ? [] : ["news_unavailable"]),
  ]);
  const risks = riskThemes(rows, riskStocks, breadth);
  return {
    version: "19.0",
    reportVersion: REPORT_VERSION,
    mode: rows.length || rankingRows.length ? (degraded.length ? "degraded" : "live") : "empty",
    dataDate: dates.at(-1) || null,
    sourceDates: {
      market: marketDates,
      rankings: isoDate(home.dataDate),
      news: isoDate(home.news?.[0]?.publishedAt || home.news?.[0]?.eventDate),
    },
    dateStatus: marketDatesAligned ? "aligned" : "partial",
    generatedAt: now.toISOString(),
    source: "existing-v19-rankings-stock-snapshots-and-news",
    updateStatus: degraded.length ? "partial" : "complete",
    report: {
      oneLine: headline,
      todayInOneSentence: headline,
      marketStrength: breadth,
      institutionalDirection: institutions,
      hotIndustries,
      watchStocks: opportunityStocks,
      opportunityStocks,
      riskStocks,
      risks,
      mainRisks: risks,
      news,
      importantNewsAndAnnouncements: news,
      watchlistChanges: watchlistChanges(parseWatchlist(watchlist), stockMap, rankingMap),
    },
    beginnerNote: `${marketDatesAligned ? "" : "各市場資料日期尚未完全一致，報告可能再次更新。"}所有說明都由公開資料與固定規則整理，目的是幫助理解，不代表保證上漲或投資建議。`,
    degraded,
  };
}

const defaultLoaders = {
  home: () => readV19Home(),
  market: (group) => readBackendMarketStocks(group),
  risks: () => readV19Rankings(new URL("https://internal.invalid/api/v19/rankings?limit=8&sort=risk_desc")),
};

async function generate(watchlist, loaders = defaultLoaders) {
  const [homeResult, listedResult, otcResult, etfResult, riskResult] = await Promise.allSettled([
    loaders.home(),
    loaders.market("listed"),
    loaders.market("otc"),
    loaders.market("etf"),
    loaders.risks(),
  ]);
  const value = (result, fallback) => result.status === "fulfilled" ? result.value : fallback;
  const report = buildDailyMarketReport({
    home: value(homeResult, { degraded: ["home_unavailable"] }),
    marketGroups: {
      listed: value(listedResult, { date: null, stocks: [] }),
      otc: value(otcResult, { date: null, stocks: [] }),
      etf: value(etfResult, { date: null, stocks: [] }),
    },
    riskPage: value(riskResult, { items: [] }),
    watchlist,
  });
  const loaderFailures = [homeResult, listedResult, otcResult, etfResult, riskResult]
    .filter((result) => result.status === "rejected").length;
  return loaderFailures
    ? { ...report, mode: report.mode === "empty" ? "empty" : "degraded", updateStatus: "partial", degraded: unique([...report.degraded, `${loaderFailures}_sources_unavailable`]) }
    : report;
}

function responseWithCache(report, status) {
  return {
    ...report,
    cache: {
      status,
      staleWhileRevalidate: status === "stale",
      freshForSeconds: FRESH_TTL_MS / 1_000,
    },
  };
}

export async function readDailyMarketReport({ watchlist = [], force = false, loaders = defaultLoaders } = {}) {
  const symbols = parseWatchlist(watchlist);
  const key = symbols.join(",") || "market";
  const now = Date.now();
  const existing = cache.get(key);
  if (!force && existing?.value && existing.freshUntil > now) {
    return responseWithCache(existing.value, "fresh");
  }
  if (!force && existing?.value && existing.staleUntil > now) {
    if (!existing.pending) {
      const pending = generate(symbols, loaders)
        .then((value) => {
          cache.set(key, { value, freshUntil: Date.now() + FRESH_TTL_MS, staleUntil: Date.now() + STALE_TTL_MS });
          return value;
        })
        .catch(() => existing.value);
      cache.set(key, { ...existing, pending });
      pending.finally(() => {
        const current = cache.get(key);
        if (current?.pending === pending) cache.set(key, { ...current, pending: null });
      }).catch(() => {});
    }
    return responseWithCache(existing.value, "stale");
  }
  if (existing?.pending) return responseWithCache(await existing.pending, "refreshed");

  const pending = generate(symbols, loaders);
  cache.set(key, { ...existing, pending, freshUntil: 0, staleUntil: existing?.staleUntil || 0 });
  try {
    const value = await pending;
    cache.set(key, { value, freshUntil: Date.now() + FRESH_TTL_MS, staleUntil: Date.now() + STALE_TTL_MS });
    return responseWithCache(value, force ? "refreshed" : "generated");
  } catch (error) {
    if (existing?.value) return responseWithCache({
      ...existing.value,
      mode: "degraded",
      updateStatus: "partial",
      degraded: unique([...(existing.value.degraded || []), "refresh_failed"]),
    }, "stale-error");
    cache.delete(key);
    throw error;
  }
}

// Stable name for the scheduled snapshot exporter.  The exporter can write
// this value to public/data/daily-report.json while the API remains a dynamic
// fail-open fallback for clients whose static snapshot is missing.
export function readDailyReport(options = {}) {
  return readDailyMarketReport(options);
}

export function refreshDailyMarketReport(options = {}) {
  return readDailyMarketReport({ ...options, watchlist: [], force: true });
}

export const dailyMarketReportInternals = {
  REPORT_VERSION,
  FRESH_TTL_MS,
  STALE_TTL_MS,
  marketBreadth,
  industryAnalysis,
  institutionalDirection,
  importantNews,
  watchlistChanges,
  clearCache() {
    cache.clear();
  },
};
