import { readdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const snapshotDir = resolve(process.env.TWSS_SNAPSHOT_DIR || resolve(root, "data/snapshots"));
const outputPath = resolve(process.env.TWSS_BACKTEST_OUTPUT || resolve(root, "public/data/backtest.json"));
const latestPath = resolve(process.env.TWSS_LATEST_SNAPSHOT || resolve(root, "public/data/latest.json"));
const horizons = [5, 10, 20];
const minimumSnapshots = Math.max(2, Number(process.env.TWSS_MINIMUM_SNAPSHOTS || 25));
const finite = (value) => value != null && Number.isFinite(Number(value));
const mean = (values) => {
  const usable = values.filter(finite).map(Number);
  return usable.length ? usable.reduce((sum, value) => sum + value, 0) / usable.length : null;
};
const round = (value, digits = 2) => finite(value) ? Number(Number(value).toFixed(digits)) : null;

async function save(payload) {
  await writeFile(outputPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  try {
    const latest = JSON.parse(await readFile(latestPath, "utf8"));
    latest.backtest = payload;
    await writeFile(latestPath, `${JSON.stringify(latest, null, 2)}\n`, "utf8");
  } catch {
    // A standalone backtest build is still valid before the first market snapshot.
  }
}

const files = (await readdir(snapshotDir)).filter((name) => /^\d{4}-\d{2}-\d{2}\.json$/.test(name)).sort();
const snapshots = [];
for (const file of files) {
  const payload = JSON.parse(await readFile(resolve(snapshotDir, file), "utf8"));
  if (Array.isArray(payload.marketPrices) && payload.dataDate && payload.snapshotCoverage?.backtestReady === true) {
    snapshots.push(payload);
  }
}

if (snapshots.length < 2) {
  await save({
    version: "17.1",
    generatedAt: new Date().toISOString(),
    status: "insufficient_history",
    readiness: "accumulating",
    snapshotCount: snapshots.length,
    observationCount: 0,
    minimumSnapshots,
    noLookAhead: true,
    message: `目前有 ${snapshots.length} 個點時快照；每個市場與期間至少需要 ${minimumSnapshots} 個成熟訊號日，統計仍在累積。`,
  });
  console.log(`Backtest waiting for signal/entry snapshots: ${snapshots.length}/2`);
  process.exit(0);
}

function priceMap(snapshot) {
  return new Map(snapshot.marketPrices.map((row) => [row.symbol, row]));
}

function marketReturn(entrySnapshot, endSnapshot, group) {
  const end = priceMap(endSnapshot);
  const returns = entrySnapshot.marketPrices
    .filter((row) => row.group === group && finite(row.open) && finite(end.get(row.symbol)?.close))
    .map((row) => (end.get(row.symbol).close / row.open - 1) * 100);
  return mean(returns);
}

function regime(snapshot, group) {
  const changes = snapshot.marketPrices.filter((row) => row.group === group).map((row) => row.change).filter(finite);
  if (!changes.length) return "unknown";
  const breadth = changes.filter((value) => value > 0).length / changes.length * 100;
  if (breadth >= 60) return "bull";
  if (breadth <= 40) return "bear";
  return "sideways";
}

const observations = [];
for (let index = 0; index < snapshots.length - 1; index += 1) {
  const signalSnapshot = snapshots[index];
  const entrySnapshot = snapshots[index + 1];
  const entryPrices = priceMap(entrySnapshot);
  for (const group of ["listed", "otc", "etf"]) {
    const ranked = (signalSnapshot.groups?.[group] || [])
      .filter((row) => row.result?.official && finite(row.result?.score))
      .sort((a, b) => b.result.score - a.result.score)
      .slice(0, 10);
    for (const candidate of ranked) {
      const entry = entryPrices.get(candidate.stock.symbol);
      // A ranking is only known after the signal-day close.  Enter at the next
      // trading day's official open; never substitute the earlier close.
      if (!finite(entry?.open)) continue;
      const returns = {};
      const excessReturns = {};
      const excursions = {};
      for (const horizon of horizons) {
        const futureSnapshot = snapshots[index + horizon];
        if (!futureSnapshot) continue;
        const future = priceMap(futureSnapshot).get(candidate.stock.symbol);
        if (!finite(future?.close)) continue;
        returns[horizon] = (future.close / entry.open - 1) * 100;
        const benchmark = marketReturn(entrySnapshot, futureSnapshot, group);
        excessReturns[horizon] = finite(benchmark) ? returns[horizon] - benchmark : null;
        const path = snapshots.slice(index + 1, index + horizon + 1)
          .map((snapshot) => priceMap(snapshot).get(candidate.stock.symbol))
          .filter(Boolean);
        excursions[horizon] = path.length ? {
          mfe: Math.max(...path.map((row) => (finite(row.high) ? row.high : row.close) / entry.open - 1)) * 100,
          mae: Math.min(...path.map((row) => (finite(row.low) ? row.low : row.close) / entry.open - 1)) * 100,
        } : null;
      }
      observations.push({
        date: signalSnapshot.dataDate,
        entryDate: entrySnapshot.dataDate,
        entryPrice: Number(entry.open),
        symbol: candidate.stock.symbol,
        name: candidate.stock.name,
        group,
        industry: candidate.stock.industry || "未分類",
        regime: regime(signalSnapshot, group),
        score: candidate.result.score,
        confidence: candidate.result.confidence,
        returns,
        excessReturns,
        excursions,
      });
    }
  }
}

function stats(rows, readyGroups = null) {
  const byHorizon = {};
  for (const horizon of horizons) {
    // Aggregate views may only consume rows from a group/horizon that already
    // passed its own maturity gate. This prevents an overall or regime average
    // from indirectly exposing an immature market's returns.
    const eligibleRows = readyGroups
      ? rows.filter((row) => readyGroups[row.group]?.[horizon]?.status === "ready")
      : rows;
    const returns = eligibleRows.map((row) => row.returns[horizon]).filter(finite);
    const excess = eligibleRows.map((row) => row.excessReturns[horizon]).filter(finite);
    const paths = eligibleRows.map((row) => row.excursions[horizon]).filter(Boolean);
    const maturedDateCount = new Set(eligibleRows
      .filter((row) => finite(row.returns[horizon]))
      .map((row) => row.date)).size;
    const ready = maturedDateCount >= minimumSnapshots;
    byHorizon[horizon] = {
      status: ready ? "ready" : "insufficient_history",
      count: ready ? returns.length : null,
      maturedDateCount,
      minimumSnapshots,
      averageReturn: ready ? round(mean(returns)) : null,
      averageExcessReturn: ready ? round(mean(excess)) : null,
      winRate: ready && returns.length ? round(returns.filter((value) => value > 0).length / returns.length * 100) : null,
      excessWinRate: ready && excess.length ? round(excess.filter((value) => value > 0).length / excess.length * 100) : null,
      averageMfe: ready ? round(mean(paths.map((row) => row.mfe))) : null,
      averageMae: ready ? round(mean(paths.map((row) => row.mae))) : null,
    };
  }
  return byHorizon;
}

function grouped(field, minimum = 1, readyGroups = null) {
  const values = [...new Set(observations.map((row) => row[field]))];
  return Object.fromEntries(values.map((value) => {
    const rows = observations.filter((row) => row[field] === value);
    return [value, rows.length >= minimum ? stats(rows, readyGroups) : null];
  }).filter(([, value]) => value));
}

const byGroup = Object.fromEntries(["listed", "otc", "etf"].map((group) => [
  group,
  stats(observations.filter((row) => row.group === group)),
]));
const readiness = Object.values(byGroup).flatMap((group) => horizons.map((horizon) => group[horizon]?.status === "ready"));
const readyPeriods = readiness.filter(Boolean).length;
const hasReadyPeriod = readyPeriods > 0;
const allPeriodsReady = readyPeriods === readiness.length;
const publicSamples = observations.slice(-120).map((row) => ({
  ...row,
  returns: Object.fromEntries(horizons.map((horizon) => [horizon,
    byGroup[row.group]?.[horizon]?.status === "ready" ? row.returns[horizon] ?? null : null,
  ])),
  excessReturns: Object.fromEntries(horizons.map((horizon) => [horizon,
    byGroup[row.group]?.[horizon]?.status === "ready" ? row.excessReturns[horizon] ?? null : null,
  ])),
  excursions: Object.fromEntries(horizons.map((horizon) => [horizon,
    byGroup[row.group]?.[horizon]?.status === "ready" ? row.excursions[horizon] ?? null : null,
  ])),
}));

await save({
  version: "17.1",
  generatedAt: new Date().toISOString(),
  status: hasReadyPeriod ? "ready" : "insufficient_history",
  readiness: allPeriodsReady ? "complete" : hasReadyPeriod ? "partial" : "accumulating",
  snapshotCount: snapshots.length,
  observationCount: observations.length,
  noLookAhead: true,
  message: allPeriodsReady
    ? null
    : hasReadyPeriod
      ? `部分市場／期間已達 ${minimumSnapshots} 個成熟訊號日；其餘統計持續累積且暫不公開。`
      : `每個市場與期間至少需要 ${minimumSnapshots} 個成熟訊號日；未達門檻不公開報酬、勝率或最大漲跌統計。`,
  methodology: "每個排名只使用訊號日已公開資料，並以次一交易日開盤價進場；未把後來公布的營收、財報或法人資料倒填。",
  horizons: stats(observations, byGroup),
  byGroup,
  byRegime: grouped("regime", 1, byGroup),
  byIndustry: grouped("industry", 10, byGroup),
  recentSamples: publicSamples,
});

console.log(`${hasReadyPeriod ? "Backtest has mature periods" : "Backtest accumulating mature signal dates"}: ${snapshots.length} snapshots, ${observations.length} ranked observations`);
