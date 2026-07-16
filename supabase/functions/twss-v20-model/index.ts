// v20 deterministic short/medium model worker. pg_cron cannot present a user
// JWT, so gateway verification is disabled; every request must still pass the
// existing private Vault-backed TWSS sync token before service-role work.
// @ts-ignore Shared pure ESM is also exercised by Node static tests.
import {
  buildMarketContext,
  scoreCacheRow,
  V20_MODEL_VERSION,
} from "../_shared/v20-model.js";
// @ts-ignore Shared pure ESM is also exercised by Node behavioral tests.
import {
  groupDateCycleKey,
  reconcileWorkerCycle,
  selectRetryTasks,
  settleWorkerAttempts,
  V20_WORKER_GROUPS,
  workerTaskKey,
} from "../_shared/v20-worker-state.js";
// @ts-ignore Pure publication guards are exercised by Node behavioral tests.
import {
  enrichmentFingerprint,
  normalizeEnrichmentSummary,
  publicationPhaseFor,
  resolveReadySourceCycle,
  shouldRunFullMarket,
} from "./publication-state.js";

const PROJECT_URL = Deno.env.get("SUPABASE_URL") || "";
const JOB_KEY = "v20_model";
const now = () => new Date().toISOString();

function adminKey() {
  try {
    const keys = JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") || "{}");
    if (keys.default) return String(keys.default);
  } catch {}
  return Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
}

const ADMIN_KEY = adminKey();
const json = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), {
  status,
  headers: {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
  },
});

type RestOptions = {
  method?: string;
  body?: unknown;
  prefer?: string;
  range?: [number, number];
};

type WorkerTask = {
  key: string;
  group_name: string;
  data_date: string;
  symbol: string;
  attempts: number;
  fromRetry: boolean;
  row: Record<string, unknown> | null;
};

type WorkerFailure = {
  key: string;
  table: string;
  group_name: string;
  data_date: string;
  symbol: string;
  error: string;
};

async function rest(path: string, options: RestOptions = {}) {
  if (!PROJECT_URL || !ADMIN_KEY) throw new Error("Supabase backend environment is incomplete");
  const headers: Record<string, string> = {
    accept: "application/json",
    "content-type": "application/json",
    apikey: ADMIN_KEY,
  };
  if (!ADMIN_KEY.startsWith("sb_secret_")) headers.authorization = `Bearer ${ADMIN_KEY}`;
  if (options.prefer) headers.prefer = options.prefer;
  if (options.range) headers.range = `${options.range[0]}-${options.range[1]}`;
  const response = await fetch(`${PROJECT_URL}/rest/v1/${path}`, {
    method: options.method || "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (!response.ok) {
    throw new Error(`Database ${response.status}: ${(await response.text()).slice(0, 300)}`);
  }
  if (response.status === 204) return { data: null, response };
  const responseText = await response.text();
  return { data: responseText ? JSON.parse(responseText) : null, response };
}

async function verifyRequest(request: Request) {
  const token = request.headers.get("x-twss-sync-token") || "";
  if (!token) return false;
  const { data } = await rest("rpc/twss_verify_sync_token", {
    method: "POST",
    body: { p_token: token },
  });
  return data === true;
}

async function claimLease(owner: string) {
  const { data } = await rest("rpc/twss_claim_sync_lease", {
    method: "POST",
    // Longer than the 300-second pg_net timeout and five-minute cron cadence,
    // so a near-timeout invocation cannot overlap the next scheduler tick.
    body: { p_job_key: JOB_KEY, p_owner: owner, p_seconds: 420 },
  });
  return data === true;
}

async function releaseLease(owner: string) {
  await rest("rpc/twss_release_sync_lease", {
    method: "POST",
    body: { p_job_key: JOB_KEY, p_owner: owner },
  });
}

async function patchState(values: Record<string, unknown>) {
  await rest(`stock_sync_state?job_key=eq.${JOB_KEY}`, {
    method: "PATCH",
    body: { ...values, updated_at: now() },
    prefer: "return=minimal",
  });
}

async function getState() {
  const { data } = await rest(`stock_sync_state?select=*&job_key=eq.${JOB_KEY}&limit=1`);
  return Array.isArray(data) ? data[0] || null : null;
}

async function loadSourceReadiness() {
  const jobs = ["universe", ...V20_WORKER_GROUPS.map((group) => `deep_${group}`)];
  const { data } = await rest(
    "stock_sync_state?select=job_key,status,cycle_date,processed_count,total_items,details" +
      `&job_key=in.(${jobs.join(",")})`,
  );
  const states = Object.fromEntries((Array.isArray(data) ? data : []).map((row) => [row.job_key, row]));
  return resolveReadySourceCycle({
    universe: states.universe,
    deepStates: Object.fromEntries(V20_WORKER_GROUPS.map((group) => [group, states[`deep_${group}`]])),
  });
}

async function loadEnrichmentSummary(dataDate: string) {
  try {
    const { data } = await rest("rpc/twss_enrichment_summary", {
      method: "POST",
      body: { p_data_date: dataDate },
    });
    const value = Array.isArray(data) ? data[0] || {} : data || {};
    return normalizeEnrichmentSummary(value);
  } catch {
    // The additive queue migration may deploy after this function.  Base
    // publication remains available and advertises base_ready until then.
    return normalizeEnrichmentSummary({ available: false });
  }
}

async function countReady(group: string, dataDate: string) {
  const { response } = await rest(
    "stock_analysis_cache?select=symbol" +
      `&group_name=eq.${group}&status=eq.ready&data_date=eq.${encodeURIComponent(dataDate)}`,
    { prefer: "count=exact", range: [0, 0] },
  );
  const total = response.headers.get("content-range")?.split("/").at(-1);
  return total && total !== "*" ? Number(total) : 0;
}

async function loadBatch(group: string, dataDate: string, afterSymbol: string, limit: number) {
  const after = afterSymbol ? `&symbol=gt.${encodeURIComponent(afterSymbol)}` : "";
  const { data } = await rest(
    "stock_analysis_cache?select=symbol,group_name,data_date,confidence,stock,analysis,result" +
      `&group_name=eq.${group}&status=eq.ready&data_date=eq.${encodeURIComponent(dataDate)}` +
      `${after}&order=symbol.asc&limit=${limit}`,
  );
  return Array.isArray(data) ? data : [];
}

async function loadRetryRow(task: Record<string, unknown>) {
  const group = String(task.group_name || "");
  const dataDate = String(task.data_date || "");
  const symbol = String(task.symbol || "");
  const { data } = await rest(
    "stock_analysis_cache?select=symbol,group_name,data_date,confidence,stock,analysis,result" +
      `&group_name=eq.${group}&status=eq.ready&data_date=eq.${encodeURIComponent(dataDate)}` +
      `&symbol=eq.${encodeURIComponent(symbol)}&limit=1`,
  );
  return Array.isArray(data) ? data[0] || null : null;
}

type DirtyQueueRow = {
  id: number;
  symbol: string;
  data_date: string;
  group_name: string;
  dirty_version: number;
  attempt_count: number;
};

async function claimDirtyBatch(owner: string, modelVersion: string, dataDate: string, limit: number) {
  const { data } = await rest("rpc/twss_claim_v20_dirty_batch", {
    method: "POST",
    body: {
      p_owner: owner,
      p_model_version: modelVersion,
      p_data_date: dataDate,
      p_limit: limit,
      p_lease_seconds: 420,
    },
  });
  return (Array.isArray(data) ? data : []) as DirtyQueueRow[];
}

async function completeDirtyBatch(owner: string, ids: number[]) {
  if (!ids.length) return 0;
  const { data } = await rest("rpc/twss_complete_v20_dirty_batch", {
    method: "POST",
    body: { p_ids: ids, p_owner: owner },
  });
  return Number(data) || 0;
}

async function retryDirtyBatch(owner: string, ids: number[], error: string) {
  if (!ids.length) return 0;
  const { data } = await rest("rpc/twss_retry_v20_dirty_batch", {
    method: "POST",
    body: {
      p_ids: ids,
      p_owner: owner,
      p_last_error: error.slice(0, 2_000),
      p_retry_after_seconds: 120,
    },
  });
  return Number(data) || 0;
}

async function loadDirtySourceRows(claims: DirtyQueueRow[]) {
  const rows: Record<string, unknown>[] = [];
  for (const group of V20_WORKER_GROUPS) {
    const groupClaims = claims.filter((claim) => claim.group_name === group);
    if (!groupClaims.length) continue;
    const symbols = groupClaims.map((claim) => encodeURIComponent(claim.symbol)).join(",");
    const dataDate = groupClaims[0].data_date;
    const { data } = await rest(
      "stock_analysis_cache?select=symbol,group_name,data_date,confidence,stock,analysis,result" +
        `&group_name=eq.${group}&status=eq.ready&data_date=eq.${encodeURIComponent(dataDate)}` +
        `&symbol=in.(${symbols})&limit=${Math.min(groupClaims.length, 500)}`,
    );
    if (Array.isArray(data)) rows.push(...data);
  }
  return rows;
}

async function fetchAll(path: string, pageSize = 800, maximum = 5_000) {
  const output: Record<string, unknown>[] = [];
  for (let offset = 0; offset < maximum; offset += pageSize) {
    const { data } = await rest(path, { range: [offset, offset + pageSize - 1] });
    const rows = Array.isArray(data) ? data : [];
    output.push(...rows);
    if (rows.length < pageSize) break;
  }
  return output;
}

async function cycleCompleteness(dataDate: string) {
  const rows = await fetchAll(
    "v20_model_signals?select=completeness" +
      `&signal_date=eq.${encodeURIComponent(dataDate)}` +
      `&model_version=eq.${encodeURIComponent(V20_MODEL_VERSION)}`,
    1_000,
    10_000,
  );
  const values = rows.map((row) => Number(row.completeness)).filter(Number.isFinite);
  if (!values.length) return 0;
  return Number((values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(2));
}

async function loadMarketContext(dataDate: string) {
  const { data: existing } = await rest(
    `v20_market_context?select=*&data_date=eq.${encodeURIComponent(dataDate)}` +
      `&model_version=eq.${encodeURIComponent(V20_MODEL_VERSION)}&limit=1`,
  );
  if (Array.isArray(existing) && existing[0]) return existing[0];

  const snapshots = await fetchAll(
    "stock_snapshots?select=symbol,market,instrument_type,change_pct,trade_value,volume,institutional_buy" +
      `&trade_date=eq.${encodeURIComponent(dataDate)}&order=symbol.asc`,
  );
  const context = buildMarketContext(snapshots, dataDate);
  await rest("v20_market_context?on_conflict=data_date,model_version", {
    method: "POST",
    body: [context],
    prefer: "resolution=merge-duplicates,return=minimal",
  });
  return context;
}

async function loadRecentNews(dataDate: string) {
  const since = new Date(`${dataDate}T00:00:00+08:00`);
  since.setUTCDate(since.getUTCDate() - 7);
  const through = new Date(`${dataDate}T23:59:59.999+08:00`);
  const { data } = await rest(
    "v19_news_items?select=symbols,sentiment_score,published_at" +
      `&published_at=gte.${encodeURIComponent(since.toISOString())}` +
      `&published_at=lte.${encodeURIComponent(through.toISOString())}` +
      "&order=published_at.desc&limit=500",
  );
  return Array.isArray(data) ? data : [];
}

async function loadCalibrations(dataDate: string) {
  const { data } = await rest(
    "v20_calibration_buckets?select=*" +
      `&model_version=eq.${encodeURIComponent(V20_MODEL_VERSION)}` +
      `&calibration_date=lte.${encodeURIComponent(dataDate)}` +
      "&order=calibration_date.desc&limit=2000",
  );
  return Array.isArray(data) ? data : [];
}

function taskFromOutput(row: Record<string, unknown>) {
  return {
    group_name: String(row.group_name || ""),
    data_date: String(row.signal_date || row.as_of_date || ""),
    symbol: String(row.symbol || ""),
  };
}

function addFailure(
  failures: WorkerFailure[],
  table: string,
  task: Record<string, unknown>,
  error: unknown,
) {
  const normalized = taskFromOutput(task);
  const key = workerTaskKey(normalized);
  failures.push({
    key,
    table,
    ...normalized,
    error: (error instanceof Error ? error.message : String(error)).slice(0, 240),
  });
}

type IsolationBudget = { remaining: number };

async function upsertWithIsolation(
  table: string,
  rows: Record<string, unknown>[],
  conflict: string,
  failures: WorkerFailure[],
  budget: IsolationBudget,
): Promise<number> {
  if (!rows.length) return 0;
  const sourceGroups = new Map<string, Record<string, unknown>[]>();
  for (const row of rows) {
    const key = workerTaskKey(taskFromOutput(row));
    sourceGroups.set(key, [...(sourceGroups.get(key) || []), row]);
  }
  if (budget.remaining <= 0) {
    for (const groupedRows of sourceGroups.values()) {
      addFailure(failures, table, groupedRows[0], "bounded_isolation_budget_exhausted");
    }
    return 0;
  }
  budget.remaining -= 1;
  try {
    await rest(`${table}?on_conflict=${conflict}`, {
      method: "POST",
      body: rows,
      prefer: "resolution=merge-duplicates,return=minimal",
    });
    return rows.length;
  } catch (error) {
    const groups = [...sourceGroups.values()];
    if (groups.length === 1) {
      addFailure(failures, table, groups[0][0], error);
      return 0;
    }
    const middle = Math.ceil(groups.length / 2);
    const left = groups.slice(0, middle).flat();
    const right = groups.slice(middle).flat();
    return await upsertWithIsolation(table, left, conflict, failures, budget) +
      await upsertWithIsolation(table, right, conflict, failures, budget);
  }
}

async function refreshRankings(dataDate: string) {
  const { data } = await rest("rpc/twss_v20_refresh_rankings", {
    method: "POST",
    body: { p_ranking_date: dataDate, p_model_version: V20_MODEL_VERSION },
  });
  return data;
}

async function evaluateMaturedSignals(asOfDate: string) {
  const { data } = await rest("rpc/twss_v20_evaluate_signal_outcomes", {
    method: "POST",
    body: {
      p_as_of_date: asOfDate,
      p_model_version: V20_MODEL_VERSION,
      p_model_key: null,
      p_limit: 200,
    },
  });
  return data;
}

function compactError(
  failures: WorkerFailure[],
  deadLetters: Record<string, unknown>[],
  rankingErrors: string[],
  maintenanceErrors: string[] = [],
) {
  const parts = [
    ...failures.slice(0, 8).map((item) => `${item.table}/${item.key}: ${item.error}`),
    ...deadLetters.slice(-5).map((item) => `dead_letter/${item.key}: ${item.last_error}`),
    ...rankingErrors.map((item) => `ranking: ${item}`),
    ...maintenanceErrors.map((item) => `maintenance: ${item}`),
  ];
  return parts.length ? parts.join(" | ").slice(0, 2_000) : null;
}

async function processIncrementalBatch(input: {
  owner: string;
  sourceDate: string;
  limit: number;
  state: any;
  priorDetails: Record<string, unknown>;
  enrichment: ReturnType<typeof normalizeEnrichmentSummary>;
}) {
  const { owner, sourceDate, limit, state, priorDetails, enrichment } = input;
  const claims = await claimDirtyBatch(owner, V20_MODEL_VERSION, sourceDate, limit);
  if (!claims.length) {
    const phase = publicationPhaseFor(enrichment);
    await patchState({
      status: priorDetails.completedCycleStatus || state?.status || "success",
      last_error: null,
      next_run_at: null,
      details: {
        ...priorDetails,
        publicationPhase: phase,
        enrichmentPending: enrichment.unresolved,
        enrichmentFingerprint: enrichmentFingerprint(enrichment),
        lastIncrementalCheckAt: now(),
      },
    });
    return json({
      status: "maintenance",
      reason: "cycle_complete_no_dirty_symbols",
      modelVersion: V20_MODEL_VERSION,
      publishedDataDate: priorDetails.publishedDataDate || sourceDate,
      publicationPhase: phase,
      enrichmentPending: enrichment.unresolved,
      incrementalClaimed: 0,
    });
  }

  const sourceRows = await loadDirtySourceRows(claims);
  const sourceByKey = new Map(sourceRows.map((row) => [workerTaskKey({
    group_name: String(row.group_name || ""),
    data_date: String(row.data_date || ""),
    symbol: String(row.symbol || ""),
  }), row]));
  const [marketContext, newsRows, calibrationBuckets] = await Promise.all([
    loadMarketContext(sourceDate),
    loadRecentNews(sourceDate),
    loadCalibrations(sourceDate),
  ]);
  const resources = { marketContext, newsRows, calibrationBuckets };
  const failures: WorkerFailure[] = [];
  const signalRows: Record<string, unknown>[] = [];
  const universeRows: Record<string, unknown>[] = [];
  for (const claim of claims) {
    const task = {
      group_name: claim.group_name,
      signal_date: claim.data_date,
      symbol: claim.symbol,
    };
    const row = sourceByKey.get(workerTaskKey({
      group_name: claim.group_name,
      data_date: claim.data_date,
      symbol: claim.symbol,
    }));
    if (!row) {
      addFailure(failures, "source", task, "ready_source_row_not_available");
      continue;
    }
    try {
      const scored = scoreCacheRow(row, resources);
      signalRows.push(...scored.signals);
      universeRows.push(scored.universe);
    } catch (error) {
      addFailure(failures, "model", task, error);
    }
  }

  const isolationBudget = { remaining: 32 };
  const [writtenSignals, writtenUniverse] = await Promise.all([
    upsertWithIsolation(
      "v20_model_signals",
      signalRows,
      "symbol,signal_date,model_key,horizon_days,model_version",
      failures,
      isolationBudget,
    ),
    upsertWithIsolation(
      "v20_universe_membership",
      universeRows,
      "symbol,as_of_date,model_version",
      failures,
      isolationBudget,
    ),
  ]);
  const failedKeys = new Set(failures.map((failure) => failure.key));
  let successfulClaims = claims.filter((claim) => !failedKeys.has(workerTaskKey({
    group_name: claim.group_name,
    data_date: claim.data_date,
    symbol: claim.symbol,
  })));
  let ranking: unknown = null;
  let rankingError: string | null = null;
  if (successfulClaims.length) {
    try {
      ranking = await refreshRankings(sourceDate);
    } catch (error) {
      rankingError = (error instanceof Error ? error.message : String(error)).slice(0, 500);
      successfulClaims = [];
    }
  }

  const successfulIds = successfulClaims.map((claim) => Number(claim.id));
  const failedIds = claims
    .filter((claim) => !successfulIds.includes(Number(claim.id)))
    .map((claim) => Number(claim.id));
  const retryError = [
    rankingError ? `ranking: ${rankingError}` : "",
    ...failures.slice(0, 8).map((failure) => `${failure.key}: ${failure.error}`),
  ].filter(Boolean).join(" | ").slice(0, 2_000) || "incremental_rescore_failed";
  const [completedDirty, retriedDirty] = await Promise.all([
    completeDirtyBatch(owner, successfulIds),
    retryDirtyBatch(owner, failedIds, retryError),
  ]);
  const phase = publicationPhaseFor(enrichment);
  const incrementalError = failedIds.length ? retryError : null;
  await patchState({
    status: incrementalError ? "partial" : priorDetails.completedCycleStatus || "success",
    last_error: incrementalError,
    last_success_at: successfulIds.length ? now() : state?.last_success_at || null,
    next_run_at: failedIds.length ? new Date(Date.now() + 2 * 60_000).toISOString() : null,
    details: {
      ...priorDetails,
      publicationPhase: phase,
      enrichmentPending: enrichment.unresolved,
      enrichmentFingerprint: enrichmentFingerprint(enrichment),
      lastIncrementalAt: now(),
      lastIncremental: {
        claimed: claims.length,
        completed: completedDirty,
        retried: retriedDirty,
        writtenSignals,
        writtenUniverse,
        rankingRefreshed: rankingError === null && successfulIds.length > 0,
      },
    },
  });
  return json({
    status: incrementalError ? "partial" : "success",
    reason: "incremental_dirty_symbols",
    modelVersion: V20_MODEL_VERSION,
    publishedDataDate: priorDetails.publishedDataDate || sourceDate,
    publicationPhase: phase,
    enrichmentPending: enrichment.unresolved,
    incrementalClaimed: claims.length,
    incrementalCompleted: completedDirty,
    incrementalRetried: retriedDirty,
    writtenSignals,
    writtenUniverse,
    ranking,
  });
}

Deno.serve(async (request: Request) => {
  if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
  if (!await verifyRequest(request).catch(() => false)) return json({ error: "unauthorized" }, 401);

  const owner = crypto.randomUUID();
  if (!await claimLease(owner)) return json({ status: "skipped", reason: "active_lease" }, 202);

  try {
    const body = await request.json().catch(() => ({}));
    const configuredLimit = Number(Deno.env.get("TWSS_V20_BATCH_LIMIT")) || 250;
    const limit = Math.max(5, Math.min(500, Number(body?.limit) || configuredLimit));
    const force = body?.force === true;
    const [state, readiness] = await Promise.all([getState(), loadSourceReadiness()]);
    const priorDetails = state?.details && typeof state.details === "object" ? state.details : {};
    if (!readiness.ready || !readiness.sourceDate) {
      await patchState({
        status: "pending",
        next_run_at: new Date(Date.now() + 2 * 60_000).toISOString(),
        last_error: null,
        details: {
          ...priorDetails,
          publicationPhase: priorDetails.publishedDataDate ? "cached" : "cached",
          targetSourceDates: readiness.sourceDates,
          sourceReadiness: {
            reason: readiness.reason,
            missingGroups: readiness.missingGroups,
            completionKeys: readiness.completionKeys,
          },
        },
      });
      return json({
        status: "pending",
        reason: readiness.reason,
        missingGroups: readiness.missingGroups,
        sourceDates: readiness.sourceDates,
        completionKeys: readiness.completionKeys,
        publicationPhase: priorDetails.publishedDataDate ? "cached" : "cached",
        publishedDataDate: priorDetails.publishedDataDate || null,
        modelVersion: V20_MODEL_VERSION,
      }, 202);
    }

    const sourceDate = String(readiness.sourceDate);
    const sourceDates = Object.fromEntries(V20_WORKER_GROUPS.map((group) => [group, sourceDate]));
    const sourceKey = groupDateCycleKey(sourceDates, V20_MODEL_VERSION);
    const enrichment = await loadEnrichmentSummary(sourceDate);
    const currentEnrichmentFingerprint = enrichmentFingerprint(enrichment);
    if (!shouldRunFullMarket({
      force,
      completedCycleKey: String(priorDetails.completedCycleKey || ""),
      sourceKey,
    })) {
      return await processIncrementalBatch({
        owner,
        sourceDate,
        limit,
        state,
        priorDetails,
        enrichment,
      });
    }

    const storedCycle = priorDetails.workerCycle && typeof priorDetails.workerCycle === "object"
      ? priorDetails.workerCycle
      : null;
    let previousCycle = null;
    if (!force && storedCycle?.completed !== true) {
      try {
        if (groupDateCycleKey(storedCycle.groupDates, V20_MODEL_VERSION) === sourceKey &&
          storedCycle.cycleKey === sourceKey) previousCycle = storedCycle;
      } catch {}
    }
    const totalPairs = await Promise.all(V20_WORKER_GROUPS.map(async (group) => [
      group,
      await countReady(group, sourceDate),
    ]));
    const totals = Object.fromEntries(totalPairs);
    const emptyGroups = V20_WORKER_GROUPS.filter((group) => Number(totals[group] || 0) <= 0);
    if (emptyGroups.length) {
      await patchState({
        status: "pending",
        next_run_at: new Date(Date.now() + 2 * 60_000).toISOString(),
        last_error: null,
        details: {
          ...priorDetails,
          publicationPhase: priorDetails.publishedDataDate ? "cached" : "cached",
          targetDataDate: sourceDate,
          targetSourceDates: { ...sourceDates, universe: sourceDate },
          sourceReadiness: { reason: "ready_cache_empty", missingGroups: emptyGroups },
        },
      });
      return json({
        status: "pending",
        reason: "ready_cache_empty",
        missingGroups: emptyGroups,
        groupDates: sourceDates,
        publicationPhase: priorDetails.publishedDataDate ? "cached" : "cached",
        publishedDataDate: priorDetails.publishedDataDate || null,
      }, 202);
    }
    const cycle: any = reconcileWorkerCycle({
      previous: previousCycle,
      latestGroupDates: sourceDates,
      totals,
      modelVersion: V20_MODEL_VERSION,
      force: force || !previousCycle,
    } as any);
    cycle.enrichmentFingerprint = previousCycle?.enrichmentFingerprint || currentEnrichmentFingerprint;
    cycle.enrichmentSummary = previousCycle?.enrichmentSummary || enrichment;
    const cycleDate = sourceDate;
    const processedBefore = V20_WORKER_GROUPS.reduce(
      (sum, group) => sum + Number(cycle.groups[group]?.processed || 0),
      0,
    );
    const total = V20_WORKER_GROUPS.reduce((sum, group) => sum + Number(totals[group] || 0), 0);

    await patchState({
      cycle_date: cycleDate,
      status: "running",
      cursor_offset: processedBefore,
      processed_count: processedBefore,
      total_items: total,
      started_at: previousCycle?.cycleKey === cycle.cycleKey && state?.started_at ? state.started_at : now(),
      last_error: null,
      details: {
        ...priorDetails,
        modelVersion: V20_MODEL_VERSION,
        batchLimit: limit,
        publicationPhase: String(priorDetails.publishedDataDate || "") === sourceDate
          ? publicationPhaseFor(enrichment)
          : "cached",
        targetDataDate: sourceDate,
        targetSourceDates: { ...sourceDates, universe: sourceDate },
        sourceReadiness: {
          reason: readiness.reason,
          missingGroups: [],
          completionKeys: readiness.completionKeys,
        },
        retryPolicy: { maxAttempts: 3, maxQueue: 300, retryShare: "25%-capped-at-10" },
        probabilityPolicy: "walk-forward-or-deterministic-quant-bootstrap",
        workerCycle: cycle,
      },
    });

    const freshWasComplete = V20_WORKER_GROUPS.every((group) => cycle.groups[group].complete === true);
    const retryPlan = selectRetryTasks(cycle.retryQueue, limit, freshWasComplete);
    const retryTasks = await Promise.all(retryPlan.selected.map(async (item: Record<string, unknown>) => {
      const row = await loadRetryRow(item).catch(() => null);
      return {
        key: workerTaskKey(item),
        group_name: String(item.group_name),
        data_date: String(item.data_date),
        symbol: String(item.symbol),
        attempts: Number(item.attempts) || 0,
        fromRetry: true,
        row,
      } satisfies WorkerTask;
    }));

    let freshBudget = Math.max(0, limit - retryTasks.length);
    const freshTasks: WorkerTask[] = [];
    const activeGroups = V20_WORKER_GROUPS.filter((group) => !cycle.groups[group].complete);
    for (let index = 0; index < activeGroups.length && freshBudget > 0; index += 1) {
      const group = activeGroups[index];
      const groupsLeft = activeGroups.length - index;
      const share = Math.max(1, Math.floor(freshBudget / groupsLeft));
      const progress = cycle.groups[group];
      const rows = await loadBatch(group, progress.dataDate, progress.cursor, share);
      for (const row of rows) {
        const task = {
          group_name: group,
          data_date: String(row.data_date || progress.dataDate),
          symbol: String(row.symbol),
        };
        freshTasks.push({
          key: workerTaskKey(task),
          ...task,
          attempts: 0,
          fromRetry: false,
          row,
        });
      }
      freshBudget -= rows.length;
      const nextProcessed = Number(progress.processed || 0) + rows.length;
      if (rows.length) progress.cursor = String(rows.at(-1)?.symbol || progress.cursor || "");
      progress.processed = nextProcessed;
      progress.total = Number(totals[group] || 0);
      if (rows.length < share) {
        if (nextProcessed < progress.total) {
          // The ready set grew behind the keyset cursor. A bounded full rescan
          // is idempotent and prevents late, lower-sorted symbols from vanishing.
          progress.cursor = "";
          progress.processed = 0;
          progress.complete = false;
          progress.scanPass = Number(progress.scanPass || 1) + 1;
        } else {
          progress.complete = true;
        }
      }
    }

    const tasks = [...retryTasks, ...freshTasks];
    const dates = [...new Set(tasks.filter((task) => task.row).map((task) => task.data_date))];
    const dateResources = new Map<string, Record<string, unknown>>();
    await Promise.all(dates.map(async (dataDate) => {
      const [marketContext, newsRows, calibrationBuckets] = await Promise.all([
        loadMarketContext(dataDate),
        loadRecentNews(dataDate),
        loadCalibrations(dataDate),
      ]);
      dateResources.set(dataDate, { marketContext, newsRows, calibrationBuckets });
    }));

    const failures: WorkerFailure[] = [];
    const signalRows: Record<string, unknown>[] = [];
    const universeRows: Record<string, unknown>[] = [];
    for (const task of tasks) {
      if (!task.row) {
        addFailure(failures, "source", {
          group_name: task.group_name,
          signal_date: task.data_date,
          symbol: task.symbol,
        }, "ready_source_row_not_available");
        continue;
      }
      try {
        const resources = dateResources.get(task.data_date) || {};
        const scored = scoreCacheRow(task.row, resources);
        signalRows.push(...scored.signals);
        universeRows.push(scored.universe);
      } catch (error) {
        addFailure(failures, "model", {
          group_name: task.group_name,
          signal_date: task.data_date,
          symbol: task.symbol,
        }, error);
      }
    }

    const isolationBudget = { remaining: 32 };
    const [writtenSignals, writtenUniverse] = await Promise.all([
      upsertWithIsolation(
        "v20_model_signals",
        signalRows,
        "symbol,signal_date,model_key,horizon_days,model_version",
        failures,
        isolationBudget,
      ),
      upsertWithIsolation(
        "v20_universe_membership",
        universeRows,
        "symbol,as_of_date,model_version",
        failures,
        isolationBudget,
      ),
    ]);

    const failureByKey = new Map<string, string>();
    for (const failure of failures) {
      const prior = failureByKey.get(failure.key);
      failureByKey.set(failure.key, prior ? `${prior}; ${failure.error}`.slice(0, 240) : failure.error);
    }
    const settled: any = settleWorkerAttempts({
      baseQueue: retryPlan.remaining,
      tasks,
      failureByKey,
      deadLetters: cycle.deadLetters,
      attemptLog: cycle.attemptLog,
      at: now(),
    } as any);
    cycle.retryQueue = settled.retryQueue;
    cycle.deadLetters = settled.deadLetters;
    cycle.attemptLog = settled.attemptLog;

    const freshComplete = V20_WORKER_GROUPS.every((group) => cycle.groups[group].complete === true);
    const readyToRefresh = freshComplete && cycle.retryQueue.length === 0;
    const ranking: Record<string, unknown>[] = [];
    const rankingErrors: string[] = [];
    const maintenanceErrors: string[] = [];
    let outcomeEvaluation: unknown = null;
    if (readyToRefresh) {
      try {
        // This RPC replaces one same-date snapshot inside a transaction.  The
        // public pointer below only advances after it succeeds, so home and
        // both ranking models cannot observe a half-published cycle.
        ranking.push(await refreshRankings(sourceDate));
      } catch (error) {
        rankingErrors.push(`${sourceDate}: ${error instanceof Error ? error.message : String(error)}`.slice(0, 300));
      }
      if (rankingErrors.length === 0) {
        try {
          outcomeEvaluation = await evaluateMaturedSignals(sourceDate);
        } catch (error) {
          maintenanceErrors.push(
            `outcome_evaluation: ${error instanceof Error ? error.message : String(error)}`.slice(0, 300),
          );
        }
      }
    }
    const complete = readyToRefresh && rankingErrors.length === 0;
    cycle.completed = complete;
    const status = complete
      ? cycle.deadLetters.length || maintenanceErrors.length ? "partial" : "success"
      : failures.length || rankingErrors.length ? "partial" : "running";
    const processed = V20_WORKER_GROUPS.reduce(
      (sum, group) => sum + Number(cycle.groups[group]?.processed || 0),
      0,
    );
    const targetEnrichment = normalizeEnrichmentSummary(cycle.enrichmentSummary || enrichment);
    const publishedCompleteness = complete
      ? await cycleCompleteness(sourceDate).catch(() => Number(priorDetails.dataCompleteness) || 0)
      : Number(priorDetails.dataCompleteness) || 0;
    const details: Record<string, unknown> = {
      ...priorDetails,
      modelVersion: V20_MODEL_VERSION,
      batchLimit: limit,
      publicationPhase: String(priorDetails.publishedDataDate || "") === sourceDate
        ? publicationPhaseFor(enrichment)
        : "cached",
      enrichmentPending: String(priorDetails.publishedDataDate || "") === sourceDate
        ? enrichment.unresolved
        : Number(priorDetails.enrichmentPending) || 0,
      targetDataDate: sourceDate,
      targetSourceDates: { ...sourceDates, universe: sourceDate },
      sourceReadiness: {
        reason: readiness.reason,
        missingGroups: [],
        completionKeys: readiness.completionKeys,
      },
      retryPolicy: { maxAttempts: 3, maxQueue: 300, retryShare: "25%-capped-at-10" },
      probabilityPolicy: "walk-forward-or-deterministic-quant-bootstrap",
      writtenSignals,
      writtenUniverse,
      ranking,
      outcomeEvaluation,
      maintenanceErrors,
      workerCycle: cycle,
    };
    if (complete) {
      const publishedAt = now();
      const samePublishedDate = String(priorDetails.publishedDataDate || "") === sourceDate;
      const publicationPhase = publicationPhaseFor(targetEnrichment);
      details.completedCycleKey = cycle.cycleKey;
      details.completedCycleStatus = status;
      details.completedCycleAt = publishedAt;
      details.publishedCycleKey = cycle.cycleKey;
      details.publishedDataDate = sourceDate;
      details.publicationPhase = publicationPhase;
      details.baseCompletedAt = samePublishedDate && priorDetails.baseCompletedAt
        ? priorDetails.baseCompletedAt
        : publishedAt;
      details.enrichmentCompletedAt = publicationPhase === "complete"
        ? samePublishedDate && priorDetails.enrichmentCompletedAt
          ? priorDetails.enrichmentCompletedAt
          : publishedAt
        : null;
      details.enrichmentPending = targetEnrichment.unresolved;
      details.enrichmentFingerprint = String(cycle.enrichmentFingerprint || currentEnrichmentFingerprint);
      details.sourceDates = { ...sourceDates, universe: sourceDate };
      details.dataCompleteness = publishedCompleteness;
      details.publishedAt = publishedAt;
    }
    const terminalError = compactError(failures, cycle.deadLetters, rankingErrors, maintenanceErrors);

    await patchState({
      status,
      cursor_offset: processed,
      processed_count: processed,
      total_items: total,
      last_symbol: complete ? null : String(freshTasks.at(-1)?.key || retryTasks.at(-1)?.key || "") || null,
      last_error: terminalError,
      last_success_at: writtenSignals || writtenUniverse ? now() : state?.last_success_at || null,
      next_run_at: complete ? null : new Date(Date.now() + 2 * 60_000).toISOString(),
      cycle_number: Number(state?.cycle_number || 0) + (complete ? 1 : 0),
      details,
    });

    return json({
      status,
      groupDates: cycle.groupDates,
      modelVersion: V20_MODEL_VERSION,
      attempted: tasks.length,
      freshAttempted: freshTasks.length,
      retryAttempted: retryTasks.length,
      processed,
      total,
      writtenSignals,
      writtenUniverse,
      retryQueued: cycle.retryQueue.length,
      deadLetters: cycle.deadLetters.length,
      failures: failures.length,
      complete,
      publicationPhase: details.publicationPhase,
      baseCompletedAt: details.baseCompletedAt || null,
      enrichmentCompletedAt: details.enrichmentCompletedAt || null,
      enrichmentPending: details.enrichmentPending,
      sourceDates: details.sourceDates || priorDetails.sourceDates || { ...sourceDates, universe: sourceDate },
      dataCompleteness: details.dataCompleteness || 0,
      ranking,
      outcomeEvaluation,
      maintenanceErrors,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await patchState({ status: "error", last_error: message.slice(0, 2_000) }).catch(() => undefined);
    console.error("[v20-model] batch failed", { error: message, loggedAt: now() });
    return json({ status: "error", code: "v20_model_batch_failed" }, 502);
  } finally {
    await releaseLease(owner).catch(() => undefined);
  }
});
