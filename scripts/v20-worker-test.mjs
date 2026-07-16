import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  groupDateCycleKey,
  reconcileWorkerCycle,
  selectRetryTasks,
  settleWorkerAttempts,
  V20_MAX_ATTEMPTS,
  V20_WORKER_GROUPS,
  workerTaskKey,
} from "../supabase/functions/_shared/v20-worker-state.js";
import {
  buildMarketContext,
  V20_MODEL_VERSION,
} from "../supabase/functions/_shared/v20-model.js";

const latest = { listed: "2026-07-16", otc: "2026-07-15", etf: "2026-07-14" };
const key = groupDateCycleKey(latest, V20_MODEL_VERSION);
assert.equal(
  key,
  "20.0|listed=2026-07-16|otc=2026-07-15|etf=2026-07-14",
  "the cycle key must preserve each market group's real date",
);
assert.equal(V20_MODEL_VERSION, "20.0");
assert.deepEqual(V20_WORKER_GROUPS, ["listed", "otc", "etf"]);

const started = reconcileWorkerCycle({
  latestGroupDates: latest,
  totals: { listed: 1_000, otc: 800, etf: 300 },
  modelVersion: V20_MODEL_VERSION,
});
started.groups.listed.cursor = "2330";
started.groups.listed.processed = 12;

const newer = { listed: "2026-07-17", otc: "2026-07-16", etf: "2026-07-15" };
const retained = reconcileWorkerCycle({
  previous: started,
  latestGroupDates: newer,
  totals: { listed: 1_000, otc: 800, etf: 300 },
  modelVersion: V20_MODEL_VERSION,
});
assert.deepEqual(retained.groupDates, latest, "an unfinished mixed-date cycle must not be starved by newer data");
assert.equal(retained.groups.listed.cursor, "2330", "each group must keep its own keyset cursor");
assert.equal(retained.groups.otc.cursor, "");

started.groups.listed.complete = true;
const readyCountChanged = reconcileWorkerCycle({
  previous: started,
  latestGroupDates: latest,
  totals: { listed: 1_001, otc: 800, etf: 300 },
  modelVersion: V20_MODEL_VERSION,
});
assert.equal(readyCountChanged.groups.listed.complete, false, "late ready rows must reopen a completed group scan");
assert.equal(readyCountChanged.groups.listed.cursor, "", "late lower-sorted symbols require a safe idempotent rescan");
assert.equal(readyCountChanged.groups.listed.scanPass, 2);

const task = {
  key: workerTaskKey({ group_name: "otc", data_date: "2026-07-15", symbol: "6488" }),
  group_name: "otc",
  data_date: "2026-07-15",
  symbol: "6488",
  attempts: 0,
  fromRetry: false,
};
let outcome = settleWorkerAttempts({
  tasks: [task],
  failureByKey: new Map([[task.key, "transient write failure"]]),
  at: "2026-07-16T00:00:00.000Z",
});
assert.equal(outcome.retryQueue.length, 1, "a failed source row must survive cursor advancement in the retry queue");
assert.equal(outcome.retryQueue[0].attempts, 1);

for (let attempt = 2; attempt <= V20_MAX_ATTEMPTS; attempt += 1) {
  const retry = { ...outcome.retryQueue[0], fromRetry: true };
  outcome = settleWorkerAttempts({
    tasks: [retry],
    failureByKey: new Map([[task.key, `failure ${attempt}`]]),
    deadLetters: outcome.deadLetters,
    attemptLog: outcome.attemptLog,
    at: `2026-07-16T00:0${attempt}:00.000Z`,
  });
}
assert.equal(outcome.retryQueue.length, 0, "retry work must be bounded");
assert.equal(outcome.deadLetters.length, 1, "terminal failure must be explicit rather than silently complete");
assert.equal(outcome.deadLetters[0].attempts, V20_MAX_ATTEMPTS);
assert.equal(outcome.attemptLog.at(-1).outcome, "dead_letter");

const retrySuccess = settleWorkerAttempts({
  tasks: [{ ...task, attempts: 1, fromRetry: true }],
  failureByKey: new Map(),
  at: "2026-07-16T00:10:00.000Z",
});
assert.equal(retrySuccess.retryQueue.length, 0);
assert.equal(retrySuccess.attemptLog[0].outcome, "retry_succeeded");

const queue = Array.from({ length: 30 }, (_, index) => ({ ...task, key: `${task.key}:${index}` }));
assert.equal(selectRetryTasks(queue, 40, false).selected.length, 10, "retries cannot consume the whole live batch");
assert.equal(selectRetryTasks(queue, 5, false).selected.length, 1);

const regimes = [
  buildMarketContext([{ market: "listed", change_pct: 10, volume: 1 }], "2026-07-16", { available: true, score: 100 }).regime,
  buildMarketContext([], "2026-07-16", { available: false, score: 0 }).regime,
  buildMarketContext([{ market: "listed", change_pct: -10, volume: 1 }], "2026-07-16", { available: true, score: -100 }).regime,
];
for (const regime of regimes) {
  assert.ok(["strong_bull", "bull", "sideways", "bear", "strong_bear"].includes(regime));
  assert.ok(!["bullish", "range", "bearish"].includes(regime), "worker and backtest regime names must match");
}

const [workerSource, migration] = await Promise.all([
  readFile(new URL("../supabase/functions/twss-v20-model/index.ts", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260716021553_add_v20_quant_models.sql", import.meta.url), "utf8"),
]);
assert.match(workerSource, /latestGroupDates\(\)/);
assert.match(workerSource, /group_name=eq\.\$\{group\}/);
assert.doesNotMatch(workerSource, /async function latestDataDate/);
assert.match(workerSource, /for \(const dataDate of cycle\.involvedDates\)/);
assert.match(workerSource, /x-twss-sync-token/);
assert.match(workerSource, /resolution=merge-duplicates/);
assert.match(migration, /'strong_bull', 'bull', 'sideways', 'bear', 'strong_bear'/);
assert.match(migration, /"maxAttempts":3/);

console.log("v20 worker tests passed");
