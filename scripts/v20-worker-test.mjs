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
import {
  enrichmentFingerprint,
  normalizeEnrichmentSummary,
  publicationPhaseFor,
  resolveReadySourceCycle,
  shouldRunFullMarket,
} from "../supabase/functions/twss-v20-model/publication-state.js";

const latest = { listed: "2026-07-16", otc: "2026-07-16", etf: "2026-07-16" };
const key = groupDateCycleKey(latest, V20_MODEL_VERSION);
assert.equal(
  key,
  "20.0|listed=2026-07-16|otc=2026-07-16|etf=2026-07-16",
  "a publication cycle must use one point-in-time date",
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

const newer = { listed: "2026-07-17", otc: "2026-07-17", etf: "2026-07-17" };
const retained = reconcileWorkerCycle({
  previous: started,
  latestGroupDates: newer,
  totals: { listed: 1_000, otc: 800, etf: 300 },
  modelVersion: V20_MODEL_VERSION,
});
assert.deepEqual(retained.groupDates, latest, "an unfinished same-date cycle must not be starved by newer data");
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

const deepStates = Object.fromEntries(V20_WORKER_GROUPS.map((group) => [group, {
  status: "success",
  cycle_date: "2026-07-16",
  details: { completedCycleKey: "2026-07-16:16.3-ultimate-data-audit" },
}]));
const readySource = resolveReadySourceCycle({
  universe: {
    status: "success",
    cycle_date: "2026-07-16",
    details: { groupDates: latest },
  },
  deepStates,
});
assert.equal(readySource.ready, true);
assert.equal(readySource.sourceDate, "2026-07-16");

const mixedSource = resolveReadySourceCycle({
  universe: {
    status: "success",
    cycle_date: "2026-07-16",
    details: { groupDates: { ...latest, otc: "2026-07-15" } },
  },
  deepStates,
});
assert.equal(mixedSource.ready, false, "mixed exchange dates must never start a model cycle");
assert.equal(mixedSource.reason, "source_dates_not_aligned");

const partialSource = resolveReadySourceCycle({
  universe: {
    status: "success",
    cycle_date: "2026-07-16",
    details: { groupDates: latest },
  },
  deepStates: { ...deepStates, otc: { ...deepStates.otc, details: {} } },
});
assert.equal(partialSource.ready, false, "all three explicit completion keys are required");
assert.deepEqual(partialSource.missingGroups, ["otc"]);

const enriching = normalizeEnrichmentSummary({ total: 1_023, success: 500, pending: 500, running: 23 });
assert.equal(enriching.unresolved, 523);
assert.equal(publicationPhaseFor(enriching), "enriching");
assert.equal(publicationPhaseFor({ available: false }), "base_ready");
assert.equal(publicationPhaseFor({ total: 1_023, success: 1_023, complete: true }), "complete");
assert.notEqual(
  enrichmentFingerprint(enriching),
  enrichmentFingerprint({ total: 1_023, success: 501, pending: 499, running: 23 }),
  "enrichment progress remains useful publication metadata",
);
assert.equal(shouldRunFullMarket({ completedCycleKey: key, sourceKey: key }), false,
  "same-date enrichment progress must never restart the full-market scan");
assert.equal(shouldRunFullMarket({ completedCycleKey: key, sourceKey: `${key}-new` }), true,
  "a new source cycle must run the full market");
assert.equal(shouldRunFullMarket({ completedCycleKey: key, sourceKey: key, force: true }), true,
  "an explicit force request must run the full market");

const regimes = [
  buildMarketContext([{ market: "listed", change_pct: 10, volume: 1 }], "2026-07-16", { available: true, score: 100 }).regime,
  buildMarketContext([], "2026-07-16", { available: false, score: 0 }).regime,
  buildMarketContext([{ market: "listed", change_pct: -10, volume: 1 }], "2026-07-16", { available: true, score: -100 }).regime,
];
for (const regime of regimes) {
  assert.ok(["strong_bull", "bull", "sideways", "bear", "strong_bear"].includes(regime));
  assert.ok(!["bullish", "range", "bearish"].includes(regime), "worker and backtest regime names must match");
}

const [workerSource, migration, incrementalMigration] = await Promise.all([
  readFile(new URL("../supabase/functions/twss-v20-model/index.ts", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260716021553_add_v20_quant_models.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260716131155_v20_incremental_dirty_queue.sql", import.meta.url), "utf8"),
]);
assert.doesNotMatch(workerSource, /latestGroupDates\(\)/);
assert.match(workerSource, /loadSourceReadiness\(\)/);
assert.match(workerSource, /resolveReadySourceCycle/);
assert.match(workerSource, /Math\.min\(500,/);
assert.match(workerSource, /TWSS_V20_BATCH_LIMIT/);
assert.match(workerSource, /refreshRankings\(sourceDate\)/);
assert.doesNotMatch(workerSource, /for \(const dataDate of cycle\.involvedDates\)/);
assert.match(workerSource, /publicationPhase/);
assert.match(workerSource, /baseCompletedAt/);
assert.match(workerSource, /enrichmentCompletedAt/);
assert.match(workerSource, /x-twss-sync-token/);
assert.match(workerSource, /resolution=merge-duplicates/);
assert.match(workerSource, /shouldRunFullMarket/);
assert.match(workerSource, /twss_claim_v20_dirty_batch/);
assert.match(workerSource, /incremental_dirty_symbols/);
assert.doesNotMatch(workerSource, /publishedEnrichmentFingerprint === currentEnrichmentFingerprint/);
assert.match(migration, /'strong_bull', 'bull', 'sideways', 'bear', 'strong_bear'/);
assert.match(migration, /"maxAttempts":3/);
assert.match(incrementalMigration, /create table if not exists public\.v20_model_dirty_queue/);
assert.match(incrementalMigration, /where status in \('pending', 'error'\)/);
assert.match(incrementalMigration, /for update skip locked/);
assert.match(incrementalMigration, /dirty_version > q\.claimed_version/);
assert.match(incrementalMigration, /then 'pending' else 'error'/,
  "a newer dirty revision must survive failure of the leased revision");
assert.match(incrementalMigration, /enable row level security/);
assert.match(incrementalMigration, /to service_role/);

console.log("v20 worker tests passed");
