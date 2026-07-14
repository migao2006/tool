import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { readBackendRankings } from "../src/backend-store.js";
import { ANALYSIS_VERSION } from "../src/deep-data.js";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const url = process.env.SUPABASE_URL || "https://lfkdkdyaatdlizryiyon.supabase.co";
const key = process.env.SUPABASE_PUBLISHABLE_KEY ||
  "sb_publishable_r3h9eQIYdIqScvmc77avAg_OLgBT6lh";

async function writeJson(path, payload) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

async function writePointInTimeJson(path, payload) {
  await mkdir(dirname(path), { recursive: true });
  try {
    // A trading-date snapshot is evidence of what the model knew at its first
    // capture.  Never let a weekend, holiday, or later source correction write
    // newer information back into that historical date.
    await writeFile(path, `${JSON.stringify(payload, null, 2)}\n`, {
      encoding: "utf8",
      flag: "wx",
    });
    return { written: true, skippedExistingSnapshot: false };
  } catch (error) {
    if (error?.code !== "EEXIST") throw error;
    return { written: false, skippedExistingSnapshot: true };
  }
}

async function readMarketPrices(groupDates) {
  const dates = [...new Set(Object.values(groupDates || {}).filter(Boolean))];
  if (!dates.length) return [];
  const output = [];
  for (let offset = 0; ; offset += 1000) {
    const select = encodeURIComponent(
      "symbol,trade_date,market,instrument_type,industry,close,high,low,change_pct,raw_data",
    );
    const response = await fetch(
      `${url}/rest/v1/stock_snapshots?select=${select}&trade_date=in.(${dates.join(",")})&order=symbol.asc&limit=1000&offset=${offset}`,
      { headers: { accept: "application/json", apikey: key }, cache: "no-store" },
    );
    if (!response.ok) throw new Error(`stock_snapshots HTTP ${response.status}`);
    const rows = await response.json();
    output.push(...rows.map((row) => {
      const group = row.instrument_type === "ETF" || /^00\d{2,4}[A-Z]?$/i.test(String(row.symbol))
        ? "etf"
        : row.market === "上櫃" ? "otc" : "listed";
      return {
        symbol: String(row.symbol),
        group,
        industry: row.industry || "未分類",
        close: row.close == null ? null : Number(row.close),
        high: row.high == null ? null : Number(row.high),
        low: row.low == null ? null : Number(row.low),
        change: row.change_pct == null
          ? (row.raw_data?.change == null ? null : Number(row.raw_data.change))
          : Number(row.change_pct),
        tradeDate: row.trade_date,
      };
    }).filter((row) => row.tradeDate === groupDates[row.group]));
    if (rows.length < 1000) break;
  }
  return output;
}

const backend = await readBackendRankings(200);
const groups = Object.fromEntries(["listed", "otc", "etf"].map((group) => [
  group,
  (backend.groups?.[group] || []).filter((row) =>
    row?.analysis?.analysisVersion === ANALYSIS_VERSION && row?.stock?.symbol),
]));
const verified = Object.values(groups).reduce((sum, rows) => sum + rows.length, 0);
if (!verified) throw new Error("後端尚無 v16.3 深度結果，保留既有靜態快照");

const generatedAt = backend.generatedAt || new Date().toISOString();
const marketPrices = await readMarketPrices(backend.groupDates);
const universeState = (backend.backend?.sync || []).find((row) => row.job_key === "universe");
const eligibleCounts = universeState?.details?.eligibleCounts || {};
const verifiedCounts = backend.backend?.counts || {};
const coverageByGroup = Object.fromEntries(["listed", "otc", "etf"].map((group) => {
  const eligible = Number(eligibleCounts[group]) || 0;
  const verifiedCount = Number(verifiedCounts[group]) || 0;
  return [group, {
    eligible,
    verified: verifiedCount,
    ratio: eligible ? Number((verifiedCount / eligible).toFixed(4)) : 0,
  }];
}));
const backtestReady = Object.values(coverageByGroup).every((row) => row.eligible > 0 && row.ratio >= 0.75);
const snapshot = {
  version: "16.3",
  analysisVersion: ANALYSIS_VERSION,
  methodology: backend.methodology,
  generatedAt,
  dataDate: backend.dataDate,
  groupDates: backend.groupDates,
  universe: backend.universe,
  backend: backend.backend,
  snapshotCoverage: {
    backtestReady,
    minimumGroupRatio: 0.75,
    byGroup: coverageByGroup,
    note: backtestReady
      ? "各市場最後成功驗證覆蓋率已達封存門檻"
      : "僅更新最新備援檔；未達覆蓋門檻，不封存為回測樣本",
  },
  groups,
  disclaimer: "候選排序僅供研究，不構成投資建議、買賣邀約或獲利保證。",
};

await writeJson(resolve(root, "public/data/latest.json"), snapshot);
const day = backend.dataDate || new Date().toISOString().slice(0, 10);
const pointInTime = backtestReady
  ? await writePointInTimeJson(resolve(root, `data/snapshots/${day}.json`), {
      ...snapshot,
      capturedAt: new Date().toISOString(),
      marketPrices,
    })
  : { written: false, skippedExistingSnapshot: false, skippedIncompleteCoverage: true };
console.log(JSON.stringify({
  message: `Exported ${verified} verified v16.3 rows for ${day}`,
  dataDate: day,
  latestUpdated: true,
  snapshotWritten: pointInTime.written,
  skippedExistingSnapshot: pointInTime.skippedExistingSnapshot,
  skippedIncompleteCoverage: Boolean(pointInTime.skippedIncompleteCoverage),
  snapshotCoverage: coverageByGroup,
}));
