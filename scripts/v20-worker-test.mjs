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
import { buildV20PublicationManifests } from "../supabase/functions/_shared/v20-publication-contract.js";
import { V20_MODEL_ARTIFACT_HASH } from "../supabase/functions/_shared/v20-model-artifact.js";
import {
  enrichMarketContextWithOfficial,
  normalizeOfficialMarketPayloads,
} from "../supabase/functions/_shared/v20-market-official.js";
import {
  attachQuoteSnapshot,
  quoteSnapshotForCacheRow,
} from "../supabase/functions/_shared/v20-quote-snapshot.js";

const latest = { listed: "2026-07-16", otc: "2026-07-16", etf: "2026-07-16" };
const key = groupDateCycleKey(latest, V20_MODEL_VERSION);
assert.equal(
  key,
  "20.1|listed=2026-07-16|otc=2026-07-16|etf=2026-07-16",
  "a publication cycle must use one point-in-time date",
);
assert.equal(V20_MODEL_VERSION, "20.1");
assert.deepEqual(V20_WORKER_GROUPS, ["listed", "otc", "etf"]);

const publicationManifests = buildV20PublicationManifests({
  dataDate: "2026-07-16",
  dataCutoffAt: "2026-07-16T08:00:00Z",
  sourceDates: { listed: "2026-07-16", otc: "2026-07-16", etf: "2026-07-16" },
});
assert.ok(Object.keys(publicationManifests.sourceManifest.sources).length > 0);
assert.deepEqual(Object.keys(publicationManifests.modelManifest).slice(0, 2), ["short", "medium"]);
assert.deepEqual(publicationManifests.modelManifest.medium.publicHorizons, [10, 20, 40]);
assert.deepEqual(publicationManifests.modelManifest.medium.researchHorizons, [60]);

const officialMarket = normalizeOfficialMarketPayloads({
  twse: [
    { Date: "1150715", ClosingIndex: "45,100" },
    { Date: "1150716", OpeningIndex: "45,511.98", HighestIndex: "45,855.02", LowestIndex: "44,970.64", ClosingIndex: "45,624.98" },
  ],
  tpex: [
    { Date: "20260715", Close: "416.41" },
    { Date: "20260716", Open: "414.88", High: "414.88", Low: "404.89", Close: "407.01", Change: "-9.40" },
  ],
  taifex: [
    { Date: "20260716", Contract: "TX", "ContractMonth(Week)": "202608", Last: "45700", Change: "-366", "%": "-0.79%", Volume: "70808", SettlementPrice: "45691", OpenInterest: "106669" },
  ],
}, "2026-07-16");
assert.equal(officialMarket.taiex.value, 45_624.98);
assert.equal(officialMarket.taiex.dataDate, "2026-07-16", "ROC dates must normalize to ISO dates");
assert.equal(officialMarket.tpex.changePercent, -2.2574);
assert.equal(officialMarket.txFutures.contractMonth, "202608");
const officialContext = enrichMarketContextWithOfficial({
  status: "partial",
  completeness: 50,
  degraded_sources: ["taiex_official_index", "tpex_official_index", "tx_futures", "international_context"],
  source_dates: { snapshots: "2026-07-16" },
}, officialMarket);
assert.deepEqual(officialContext.degraded_sources, ["international_context"]);
assert.equal(officialContext.completeness, 87.5);
assert.equal(officialContext.status, "partial");

const immutableQuote = quoteSnapshotForCacheRow({
  data_date: "2026-07-16",
  stock: { priceDate: "2026-07-16", close: 25.5, change: 0.5917, volume: 17_727.214, value: 450_128_521 },
});
assert.deepEqual(immutableQuote, {
  tradeDate: "2026-07-16",
  close: 25.5,
  change: 0.5917,
  open: null,
  high: null,
  low: null,
  volume: 17_727.214,
  value: 450_128_521,
  source: "stock_analysis_cache",
});
assert.deepEqual(
  attachQuoteSnapshot(
    [{ signal_date: "2026-07-16", gate_results: { data_complete: true } }],
    { data_date: "2026-07-16", stock: { close: 25.5, priceDate: "2026-07-16" } },
  )[0].gate_results,
  { data_complete: true, quoteSnapshot: { tradeDate: "2026-07-16", close: 25.5, change: null, open: null, high: null, low: null, volume: null, value: null, source: "stock_analysis_cache" } },
  "the worker must hash the exact quote into each immutable signal before publication",
);
assert.throws(() => quoteSnapshotForCacheRow({
  data_date: "2026-07-16",
  stock: { priceDate: "2026-07-15", close: 25.5 },
}), /v20_verified_quote_required/, "a mutable or cross-date close must never enter an immutable run");
assert.throws(() => quoteSnapshotForCacheRow({
  data_date: "2026-07-16",
  stock: { priceDate: "2026-07-16", close: 25.5, high: 25 },
}), /v20_verified_quote_ohlc_invalid/);
assert.throws(() => attachQuoteSnapshot(
  [{ signal_date: "2026-07-15", gate_results: {} }],
  { data_date: "2026-07-16", stock: { priceDate: "2026-07-16", close: 25.5 } },
), /v20_signal_quote_date_mismatch/);
const horizonQuotes = attachQuoteSnapshot(
  [2, 3, 5, 10, 10, 20, 40, 60].map((horizon_days) => ({
    signal_date: "2026-07-16", horizon_days, gate_results: {},
  })),
  { data_date: "2026-07-16", stock: { priceDate: "2026-07-16", close: 25.5 } },
);
assert.equal(horizonQuotes.length, 8);
for (const signal of horizonQuotes) assert.deepEqual(signal.gate_results.quoteSnapshot, horizonQuotes[0].gate_results.quoteSnapshot);

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

const [workerSource, migration, incrementalMigration, verifiableMigration] = await Promise.all([
  readFile(new URL("../supabase/functions/twss-v20-model/index.ts", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260716021553_add_v20_quant_models.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260716131155_v20_incremental_dirty_queue.sql", import.meta.url), "utf8"),
  readFile(new URL("../supabase/migrations/20260716173332_verifiable_opportunity_snapshots.sql", import.meta.url), "utf8"),
]);
assert.doesNotMatch(workerSource, /latestGroupDates\(\)/);
assert.match(workerSource, /loadSourceReadiness\(\)/);
assert.match(workerSource, /resolveReadySourceCycle/);
assert.match(workerSource, /Math\.min\(500,/);
assert.match(workerSource, /TWSS_V20_BATCH_LIMIT/);
assert.match(workerSource, /rpc\/twss_v20_publish_recommendation_run/);
assert.match(workerSource, /rpc\/twss_v20_signal_data_cutoff/,
  "the cutoff must come from the service-only database resolver");
assert.match(workerSource, /rpc\/twss_v20_read_immutable_calibration/);
assert.match(workerSource, /rpc\/twss_v20_read_model_channels/);
assert.match(workerSource, /rpc\/twss_v20_refresh_immutable_calibration/);
assert.doesNotMatch(workerSource, /v20_calibration_buckets\?select=/,
  "v20.1 scoring must never read the mutable legacy calibration table");
assert.match(workerSource, /calibrationBeforeAt/);
assert.match(workerSource, /T23:59:59\.999\+08:00/,
  "historical scoring must not see calibration observations after that Taipei day");
assert.match(workerSource, /calibration_version:\s*resources\.calibrationVersion/);
assert.match(workerSource, /calibrationVersion:\s*input\.calibrationVersion/);
assert.match(
  workerSource,
  /shortChampion\?\.validation_status === "passed"[\s\S]{0,240}mediumChampion\?\.validation_status === "passed"[\s\S]{0,320}shortCalibrationVersion === snapshotCalibrationVersion/,
  "calibration is usable only when both passed Champions bind the same immutable snapshot",
);
assert.match(workerSource, /calibrationBuckets: championAligned \? buckets : \[\]/);
assert.match(workerSource, /calibrationVersion = championAligned \? snapshotCalibrationVersion : null/);
assert.match(workerSource, /refreshImmutableCalibration\(outcomeEvaluation\)/,
  "all outcome-drain paths must advance calibration only from immutable outcomes");
assert.equal(
  (workerSource.match(/await refreshImmutableCalibration\(outcomeEvaluation\)/g) || []).length,
  3,
  "no-dirty, incremental and complete-cycle paths must all run the bounded immutable calibration refresh",
);
assert.match(workerSource, /V20_MODEL_ARTIFACT_HASH/);
assert.ok(/^[0-9a-f]{64}$/.test(V20_MODEL_ARTIFACT_HASH));
assert.doesNotMatch(workerSource, /v20\.1-edge-model/,
  "a placeholder code identity must never be published");
assert.match(workerSource, /configuredCodeHash !== V20_MODEL_ARTIFACT_HASH/,
  "a configured deployment hash must exactly match the bundled artifact identity");
assert.match(workerSource, /rpc\/twss_v20_evaluate_immutable_outcomes/);
assert.match(workerSource, /drainImmutableOutcomeBacklog/);
assert.match(workerSource, /for \(let index = 0; index < maxBatches/,
  "matured immutable outcomes must drain in bounded batches instead of one fixed call");
assert.match(workerSource, /batchLimit = Math\.max\(1, Math\.min\(500,/);
assert.doesNotMatch(workerSource, /p_limit:\s*200/,
  "a fixed 200-row outcome call would leave the daily backlog behind");
assert.doesNotMatch(workerSource, /rpc\/twss_v20_evaluate_signal_outcomes/,
  "the worker must evaluate only immutable published recommendations");
assert.match(
  workerSource,
  /const readyToPublish = freshComplete[\s\S]{0,240}retryQueue\.length === 0[\s\S]{0,120}failures\.length === 0[\s\S]{0,120}deadLetters\.length === 0/,
  "publication must require a complete cycle with no retries, failures, or dead letters",
);
assert.match(workerSource, /const complete = readyToPublish && immutablePublication !== null && rankingErrors\.length === 0/);
assert.doesNotMatch(workerSource, /refreshRankings/,
  "the worker must not call the mutable legacy ranking refresher");
assert.doesNotMatch(workerSource, /for \(const dataDate of cycle\.involvedDates\)/);
assert.match(workerSource, /publicationPhase/);
assert.match(workerSource, /baseCompletedAt/);
assert.match(workerSource, /enrichmentCompletedAt/);
assert.match(workerSource, /x-twss-sync-token/);
assert.match(workerSource, /resolution=merge-duplicates/);
assert.match(workerSource, /marketContext: input\.marketContext/,
  "the publisher request must carry the exact market context used during scoring");
assert.match(workerSource, /v20_market_context_reload_failed/,
  "a newly inserted context must be reloaded with database timestamps before publication");
assert.match(workerSource, /shouldRunFullMarket/);
assert.match(workerSource, /twss_claim_v20_dirty_batch/);
assert.match(workerSource, /incremental_dirty_symbols/);
assert.match(workerSource, /maintenanceDisposition\(rest\)/);
assert.match(workerSource, /body\?\.maintenanceVerification === true/);
assert.match(workerSource, /row\?\.enabled === true && row\?\.phase === "verifying"/,
  "a manual release worker may bypass maintenance only during the controlled verification phase");
assert.match(workerSource, /if \(maintenance\.blocked && !verificationRun\)/);
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
assert.match(verifiableMigration, /create or replace function public\.twss_v20_publish_recommendation_run/);
assert.match(verifiableMigration, /create or replace function public\.twss_v20_signal_data_cutoff/);
assert.match(verifiableMigration, /max\(greatest\(s\.generated_at, s\.updated_at\)\)/);
assert.match(verifiableMigration, /lock table public\.v20_model_signals in share mode/);
assert.match(verifiableMigration, /v20_signal_data_cutoff_changed/,
  "the publisher must reject a staging write that wins the pre-publication race");
assert.match(verifiableMigration, /v20_calibration_version_mismatch/);
assert.match(verifiableMigration, /v_code_hash !~ '\^\[0-9a-f\]\{64\}\$'/);
assert.match(verifiableMigration, /create or replace function public\.twss_v20_evaluate_immutable_outcomes/);
assert.match(verifiableMigration, /market_context_snapshot jsonb not null/);
assert.match(verifiableMigration, /v20_market_context_mismatch/);
assert.match(
  verifiableMigration,
  /v_cycle_completeness <> 100[\s\S]*v_deadletter_count <> 0[\s\S]*jsonb_array_length\(v_terminal_errors\) <> 0[\s\S]*insert into public\.v20_publication_head/,
  "the atomic publisher must reject incomplete/error cycles before switching the publication head",
);

console.log("v20 worker tests passed");
