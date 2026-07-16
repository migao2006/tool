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

async function latestGroupDates() {
  const pairs = await Promise.all(V20_WORKER_GROUPS.map(async (group) => {
    const { data } = await rest(
      "stock_analysis_cache?select=data_date" +
        `&group_name=eq.${group}&status=eq.ready&data_date=not.is.null` +
        "&order=data_date.desc&limit=1",
    );
    const dataDate = Array.isArray(data) ? data[0]?.data_date : null;
    if (!dataDate) throw new Error(`No ready point-in-time cache is available for ${group}`);
    return [group, String(dataDate)];
  }));
  return Object.fromEntries(pairs);
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

Deno.serve(async (request: Request) => {
  if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
  if (!await verifyRequest(request).catch(() => false)) return json({ error: "unauthorized" }, 401);

  const owner = crypto.randomUUID();
  if (!await claimLease(owner)) return json({ status: "skipped", reason: "active_lease" }, 202);

  try {
    const body = await request.json().catch(() => ({}));
    const limit = Math.max(5, Math.min(100, Number(body?.limit) || 40));
    const force = body?.force === true;
    const [state, latestDates] = await Promise.all([getState(), latestGroupDates()]);
    const latestKey = groupDateCycleKey(latestDates, V20_MODEL_VERSION);
    const priorDetails = state?.details && typeof state.details === "object" ? state.details : {};
    if (!force && String(priorDetails.completedCycleKey || "") === latestKey) {
      const asOfDate = String([...Object.values(latestDates)].sort().at(-1) || "");
      let outcomeEvaluation: unknown = null;
      let maintenanceError: string | null = null;
      try {
        outcomeEvaluation = await evaluateMaturedSignals(asOfDate);
      } catch (error) {
        maintenanceError = (error instanceof Error ? error.message : String(error)).slice(0, 500);
      }
      await patchState({
        status: maintenanceError ? "partial" : priorDetails.completedCycleStatus || "success",
        last_error: maintenanceError ? `maintenance/outcome_evaluation: ${maintenanceError}` : null,
        details: {
          ...priorDetails,
          lastOutcomeEvaluation: outcomeEvaluation,
          lastOutcomeEvaluationAt: now(),
          lastOutcomeEvaluationError: maintenanceError,
        },
      });
      return json({
        status: maintenanceError ? "partial" : "maintenance",
        reason: "cycle_complete_outcome_maintenance",
        groupDates: latestDates,
        modelVersion: V20_MODEL_VERSION,
        completedStatus: priorDetails.completedCycleStatus || "success",
        outcomeEvaluation,
        maintenanceError,
      });
    }

    const previousCycle = priorDetails.workerCycle && typeof priorDetails.workerCycle === "object"
      ? priorDetails.workerCycle
      : null;
    let targetDates = latestDates;
    if (!force && previousCycle?.completed !== true) {
      try {
        if (groupDateCycleKey(previousCycle.groupDates, V20_MODEL_VERSION) === previousCycle.cycleKey) {
          targetDates = previousCycle.groupDates;
        }
      } catch {}
    }
    const totalPairs = await Promise.all(V20_WORKER_GROUPS.map(async (group) => [
      group,
      await countReady(group, targetDates[group]),
    ]));
    const totals = Object.fromEntries(totalPairs);
    const cycle: any = reconcileWorkerCycle({
      previous: previousCycle,
      latestGroupDates: latestDates,
      totals,
      modelVersion: V20_MODEL_VERSION,
      force,
    } as any);
    const cycleDate = [...Object.values(cycle.groupDates)].sort().at(-1);
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
      for (const dataDate of cycle.involvedDates) {
        try {
          ranking.push(await refreshRankings(dataDate));
        } catch (error) {
          rankingErrors.push(`${dataDate}: ${error instanceof Error ? error.message : String(error)}`.slice(0, 300));
        }
      }
      if (rankingErrors.length === 0) {
        const asOfDate = [...cycle.involvedDates].sort().at(-1) || cycleDate;
        try {
          outcomeEvaluation = await evaluateMaturedSignals(asOfDate);
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
    const details: Record<string, unknown> = {
      ...priorDetails,
      modelVersion: V20_MODEL_VERSION,
      batchLimit: limit,
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
      details.completedCycleKey = cycle.cycleKey;
      details.completedCycleStatus = status;
      details.completedCycleAt = now();
    } else if (details.completedCycleKey === cycle.cycleKey) {
      delete details.completedCycleKey;
      delete details.completedCycleStatus;
      delete details.completedCycleAt;
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
      next_run_at: complete ? null : new Date(Date.now() + 5 * 60_000).toISOString(),
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
