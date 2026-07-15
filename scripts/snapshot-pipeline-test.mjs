import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const run = promisify(execFile);
const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const fixtureRoot = await mkdtemp(resolve(tmpdir(), "twss-backtest-"));
const insufficientSnapshotDir = resolve(fixtureRoot, "snapshots-25-days");
const matureSnapshotDir = resolve(fixtureRoot, "snapshots-45-days");
const noOpenSnapshotDir = resolve(fixtureRoot, "snapshots-no-open");
const insufficientOutputPath = resolve(fixtureRoot, "backtest-25-days.json");
const matureOutputPath = resolve(fixtureRoot, "backtest-45-days.json");
const noOpenOutputPath = resolve(fixtureRoot, "backtest-no-open.json");
const latestPath = resolve(fixtureRoot, "latest.json");
await mkdir(insufficientSnapshotDir, { recursive: true });
await mkdir(matureSnapshotDir, { recursive: true });
await mkdir(noOpenSnapshotDir, { recursive: true });

const groups = [
  ["listed", "1101", "上市測試"],
  ["otc", "4101", "上櫃測試"],
  ["etf", "0050", "ETF 測試"],
];
for (let index = 0; index < 45; index += 1) {
  const date = new Date(Date.UTC(2026, 0, index + 1)).toISOString().slice(0, 10);
  const rankingGroups = {};
  const marketPrices = [];
  for (const [group, symbol, name] of groups) {
    rankingGroups[group] = [{
      stock: { symbol, name, industry: "測試產業" },
      result: { official: true, score: 80 - index / 10, confidence: 90 },
    }];
    marketPrices.push({
      symbol, group, industry: "測試產業", open: 100 + index,
      close: 101 + index, high: 102 + index, low: 99 + index, change: 1,
    });
  }
  const payload = {
    version: "17.2", dataDate: date, snapshotCoverage: { backtestReady: true },
    groups: rankingGroups, marketPrices,
  };
  await writeFile(resolve(matureSnapshotDir, `${date}.json`), JSON.stringify(payload));
  if (index < 25) {
    await writeFile(resolve(insufficientSnapshotDir, `${date}.json`), JSON.stringify(payload));
  }
  await writeFile(resolve(noOpenSnapshotDir, `${date}.json`), JSON.stringify({
    ...payload,
    marketPrices: marketPrices.map(({ open, ...row }) => row),
  }));
}

await run(process.execPath, [resolve(root, "scripts/backtest-snapshots.mjs")], {
  cwd: root,
  env: {
    ...process.env,
    TWSS_SNAPSHOT_DIR: insufficientSnapshotDir,
    TWSS_BACKTEST_OUTPUT: insufficientOutputPath,
    TWSS_LATEST_SNAPSHOT: latestPath,
  },
});

const insufficientBacktest = JSON.parse(await readFile(insufficientOutputPath, "utf8"));
assert.equal(insufficientBacktest.status, "insufficient_history");
assert.equal(insufficientBacktest.readiness, "accumulating");
assert.ok(insufficientBacktest.observationCount > 0, "official next-open observations must still accumulate");
const expectedMatureDatesAt25 = { 5: 20, 10: 15, 20: 5 };
const privateStatisticFields = [
  "count", "averageReturn", "averageExcessReturn", "winRate", "excessWinRate", "averageMfe", "averageMae",
];
for (const group of ["listed", "otc", "etf"]) {
  for (const horizon of [5, 10, 20]) {
    const period = insufficientBacktest.byGroup[group][horizon];
    assert.equal(period.status, "insufficient_history");
    assert.equal(period.maturedDateCount, expectedMatureDatesAt25[horizon]);
    for (const field of privateStatisticFields) {
      assert.equal(period[field], null, `${group}/${horizon} ${field} must stay private before 25 mature dates`);
    }
  }
}
for (const view of [
  insufficientBacktest.horizons,
  insufficientBacktest.byRegime.bull,
  insufficientBacktest.byIndustry["測試產業"],
]) {
  for (const horizon of [5, 10, 20]) {
    assert.equal(view[horizon].status, "insufficient_history");
    for (const field of privateStatisticFields) assert.equal(view[horizon][field], null);
  }
}
for (const sample of insufficientBacktest.recentSamples) {
  for (const horizon of [5, 10, 20]) {
    assert.equal(sample.returns[horizon], null);
    assert.equal(sample.excessReturns[horizon], null);
    assert.equal(sample.excursions[horizon], null);
  }
}

await run(process.execPath, [resolve(root, "scripts/backtest-snapshots.mjs")], {
  cwd: root,
  env: {
    ...process.env,
    TWSS_SNAPSHOT_DIR: matureSnapshotDir,
    TWSS_BACKTEST_OUTPUT: matureOutputPath,
    TWSS_LATEST_SNAPSHOT: latestPath,
  },
});

const matureBacktest = JSON.parse(await readFile(matureOutputPath, "utf8"));
assert.equal(matureBacktest.status, "ready");
assert.equal(matureBacktest.readiness, "complete");
for (const group of ["listed", "otc", "etf"]) {
  assert.equal(matureBacktest.byGroup[group][20].status, "ready");
  assert.equal(matureBacktest.byGroup[group][20].maturedDateCount, 25);
  assert.ok(matureBacktest.byGroup[group][20].count > 0);
  assert.notEqual(matureBacktest.byGroup[group][20].averageReturn, null);
}
const firstVisibleMatureSample = matureBacktest.recentSamples.find((sample) =>
  sample.date === "2026-01-05" && sample.group === "listed");
assert.ok(firstVisibleMatureSample, "45-day fixture must retain a mature listed sample");
assert.equal(firstVisibleMatureSample.entryPrice, 105, "entry must use the next snapshot's official open");
assert.equal(firstVisibleMatureSample.regime, "bull", "regime must use the signal snapshot");

await run(process.execPath, [resolve(root, "scripts/backtest-snapshots.mjs")], {
  cwd: root,
  env: {
    ...process.env,
    TWSS_SNAPSHOT_DIR: noOpenSnapshotDir,
    TWSS_BACKTEST_OUTPUT: noOpenOutputPath,
    TWSS_LATEST_SNAPSHOT: latestPath,
  },
});
const noOpenBacktest = JSON.parse(await readFile(noOpenOutputPath, "utf8"));
assert.equal(noOpenBacktest.status, "insufficient_history");
assert.equal(noOpenBacktest.observationCount, 0);

const [backtestSource, exporterSource, updaterSource, serviceWorker, indexHtml, appSource, smartSource, patchSource] = await Promise.all([
  readFile(resolve(root, "scripts/backtest-snapshots.mjs"), "utf8"),
  readFile(resolve(root, "scripts/export-backend-snapshot.mjs"), "utf8"),
  readFile(resolve(root, "scripts/update-market-data.mjs"), "utf8"),
  readFile(resolve(root, "public/sw.js"), "utf8"),
  readFile(resolve(root, "public/index.html"), "utf8"),
  readFile(resolve(root, "public/app.js"), "utf8"),
  readFile(resolve(root, "public/smart.js"), "utf8"),
  readFile(resolve(root, "public/patch.js"), "utf8"),
]);
assert.doesNotMatch(backtestSource, /regime\(startSnapshot/);
assert.match(backtestSource, /regime\(signalSnapshot/);
assert.match(exporterSource, /industry,open,close,high,low/);
assert.match(exporterSource, /finalCycleByGroup/);
assert.match(exporterSource, /coherentTradingDate/);
assert.match(exporterSource, /officialOpens/);
assert.match(exporterSource, /row\.dataDate/);
assert.match(updaterSource, /open: stock\.open/);
assert.match(serviceWorker, /twss-v17\.3\.3/);
assert.match(indexHtml, /\?v=17\.3\.3/);
assert.match(appSource, /sw\.js\?v=17\.3\.3/);
assert.match(smartSource, /backtest\.json\?v=17\.3\.3/);
assert.match(patchSource, /LEGACY_AI_LOCAL_STORAGE_KEYS/);
assert.doesNotMatch(patchSource, /Object\.keys\(localStorage\)|localStorage\.clear\(/,
  "legacy cleanup must never scan or clear unrelated user storage");

console.log("Snapshot pipeline tests passed: 25 mature-date gating, 45-day readiness, next-open runtime, final-cycle readiness, official open, and v17.3.3 cache busting");
