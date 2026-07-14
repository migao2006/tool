import { readdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const snapshotDir = resolve(root, "data/snapshots");
const outputPath = resolve(root, "public/data/backtest.json");
const latestPath = resolve(root, "public/data/latest.json");
const horizons = [5, 10, 20];
const minimumSnapshots = 25;
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
  if (Array.isArray(payload.marketPrices) && payload.dataDate) snapshots.push(payload);
}

if (snapshots.length < minimumSnapshots) {
  await save({
    version: "16.1",
    generatedAt: new Date().toISOString(),
    status: "insufficient_history",
    snapshotCount: snapshots.length,
    minimumSnapshots,
    noLookAhead: true,
    message: `目前有 ${snapshots.length} 個點時快照；至少 ${minimumSnapshots} 個不同交易日後才產生正式回測。`,
  });
  console.log(`Backtest waiting: ${snapshots.length}/${minimumSnapshots} snapshots`);
  process.exit(0);
}

function priceMap(snapshot) {
  return new Map(snapshot.marketPrices.map((row) => [row.symbol, row]));
}

function marketReturn(startSnapshot, endSnapshot, group) {
  const end = priceMap(endSnapshot);
  const returns = startSnapshot.marketPrices
    .filter((row) => row.group === group && finite(row.close) && finite(end.get(row.symbol)?.close))
    .map((row) => (end.get(row.symbol).close / row.close - 1) * 100);
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
for (let index = 0; index < snapshots.length - Math.max(...horizons); index += 1) {
  const startSnapshot = snapshots[index];
  const startPrices = priceMap(startSnapshot);
  for (const group of ["listed", "otc", "etf"]) {
    const ranked = (startSnapshot.groups?.[group] || [])
      .filter((row) => row.result?.official && finite(row.result?.score))
      .sort((a, b) => b.result.score - a.result.score)
      .slice(0, 10);
    for (const candidate of ranked) {
      const start = startPrices.get(candidate.stock.symbol);
      if (!finite(start?.close)) continue;
      const returns = {};
      const excessReturns = {};
      const excursions = {};
      for (const horizon of horizons) {
        const futureSnapshot = snapshots[index + horizon];
        const future = priceMap(futureSnapshot).get(candidate.stock.symbol);
        if (!finite(future?.close)) continue;
        returns[horizon] = (future.close / start.close - 1) * 100;
        const benchmark = marketReturn(startSnapshot, futureSnapshot, group);
        excessReturns[horizon] = finite(benchmark) ? returns[horizon] - benchmark : null;
        const path = snapshots.slice(index + 1, index + horizon + 1)
          .map((snapshot) => priceMap(snapshot).get(candidate.stock.symbol))
          .filter(Boolean);
        excursions[horizon] = path.length ? {
          mfe: Math.max(...path.map((row) => (finite(row.high) ? row.high : row.close) / start.close - 1)) * 100,
          mae: Math.min(...path.map((row) => (finite(row.low) ? row.low : row.close) / start.close - 1)) * 100,
        } : null;
      }
      observations.push({
        date: startSnapshot.dataDate,
        symbol: candidate.stock.symbol,
        name: candidate.stock.name,
        group,
        industry: candidate.stock.industry || "未分類",
        regime: regime(startSnapshot, group),
        score: candidate.result.score,
        confidence: candidate.result.confidence,
        returns,
        excessReturns,
        excursions,
      });
    }
  }
}

function stats(rows) {
  const byHorizon = {};
  for (const horizon of horizons) {
    const returns = rows.map((row) => row.returns[horizon]).filter(finite);
    const excess = rows.map((row) => row.excessReturns[horizon]).filter(finite);
    const paths = rows.map((row) => row.excursions[horizon]).filter(Boolean);
    byHorizon[horizon] = {
      count: returns.length,
      averageReturn: round(mean(returns)),
      averageExcessReturn: round(mean(excess)),
      winRate: returns.length ? round(returns.filter((value) => value > 0).length / returns.length * 100) : null,
      excessWinRate: excess.length ? round(excess.filter((value) => value > 0).length / excess.length * 100) : null,
      averageMfe: round(mean(paths.map((row) => row.mfe))),
      averageMae: round(mean(paths.map((row) => row.mae))),
    };
  }
  return byHorizon;
}

function grouped(field, minimum = 1) {
  const values = [...new Set(observations.map((row) => row[field]))];
  return Object.fromEntries(values.map((value) => {
    const rows = observations.filter((row) => row[field] === value);
    return [value, rows.length >= minimum ? stats(rows) : null];
  }).filter(([, value]) => value));
}

await save({
  version: "16.1",
  generatedAt: new Date().toISOString(),
  status: "ready",
  snapshotCount: snapshots.length,
  observationCount: observations.length,
  noLookAhead: true,
  methodology: "每個排名只使用該交易日收盤前已寫入快照的資料；未把後來公布的營收、財報或法人資料倒填。",
  horizons: stats(observations),
  byGroup: grouped("group"),
  byRegime: grouped("regime"),
  byIndustry: grouped("industry", 10),
  recentSamples: observations.slice(-120),
});

console.log(`Backtest ready: ${snapshots.length} snapshots, ${observations.length} ranked observations`);
