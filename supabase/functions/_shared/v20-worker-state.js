export const V20_WORKER_GROUPS = Object.freeze(["listed", "otc", "etf"]);
export const V20_MAX_ATTEMPTS = 3;
export const V20_RETRY_QUEUE_LIMIT = 300;
export const V20_ATTEMPT_LOG_LIMIT = 100;

const text = (value) => String(value ?? "").trim();

export function workerTaskKey(task) {
  const group = text(task?.group_name || task?.group);
  const dataDate = text(task?.data_date || task?.dataDate);
  const symbol = text(task?.symbol);
  if (!V20_WORKER_GROUPS.includes(group) || !dataDate || !symbol) {
    throw new Error("invalid_v20_worker_task");
  }
  return `${group}:${dataDate}:${symbol}`;
}
export function groupDateCycleKey(groupDates, modelVersion = "20.0") {
  const dates = V20_WORKER_GROUPS.map((group) => {
    const dataDate = text(groupDates?.[group]);
    if (!dataDate) throw new Error(`missing_ready_date:${group}`);
    return `${group}=${dataDate}`;
  });
  return `${text(modelVersion) || "20.0"}|${dates.join("|")}`;
}

function cleanProgress(group, dataDate, input = {}) {
  return {
    group,
    dataDate,
    cursor: text(input.cursor),
    processed: Math.max(0, Number(input.processed) || 0),
    total: Math.max(0, Number(input.total) || 0),
    complete: input.complete === true,
    scanPass: Math.max(1, Number(input.scanPass) || 1),
  };
}

function cleanRetry(item, groupDates) {
  try {
    const group = text(item?.group_name || item?.group);
    const dataDate = text(item?.data_date || item?.dataDate);
    const symbol = text(item?.symbol);
    const attempts = Math.max(0, Number(item?.attempts) || 0);
    if (!V20_WORKER_GROUPS.includes(group) || groupDates?.[group] !== dataDate || !symbol) return null;
    return {
      key: workerTaskKey({ group_name: group, data_date: dataDate, symbol }),
      group_name: group,
      data_date: dataDate,
      symbol,
      attempts,
      last_error: text(item?.last_error || item?.lastError).slice(0, 240),
      last_attempt_at: text(item?.last_attempt_at || item?.lastAttemptAt) || null,
    };
  } catch {
    return null;
  }
}

function dedupeRetries(items, groupDates, limit = V20_RETRY_QUEUE_LIMIT) {
  const byKey = new Map();
  for (const raw of Array.isArray(items) ? items : []) {
    const item = cleanRetry(raw, groupDates);
    if (!item || item.attempts >= V20_MAX_ATTEMPTS) continue;
    const prior = byKey.get(item.key);
    if (!prior || item.attempts >= prior.attempts) byKey.set(item.key, item);
  }
  return [...byKey.values()]
    .sort((a, b) => (a.last_attempt_at || "").localeCompare(b.last_attempt_at || "") || a.key.localeCompare(b.key))
    .slice(0, Math.max(1, Number(limit) || V20_RETRY_QUEUE_LIMIT));
}

/**
 * Starts a cycle from each market group's own latest ready date. An unfinished
 * cycle keeps its target vector stable so a faster group cannot starve a group
 * whose official data date is one session behind.
 */
export function reconcileWorkerCycle({ previous, latestGroupDates, totals = {}, modelVersion = "20.0", force = false }) {
  const latestKey = groupDateCycleKey(latestGroupDates, modelVersion);
  const old = previous && typeof previous === "object" ? previous : {};
  const oldDates = old.groupDates && typeof old.groupDates === "object" ? old.groupDates : {};
  const oldKey = (() => {
    try {
      return groupDateCycleKey(oldDates, modelVersion);
    } catch {
      return "";
    }
  })();
  const retainActive = !force && old.completed !== true && oldKey && oldKey === text(old.cycleKey);
  const groupDates = retainActive ? { ...oldDates } : { ...latestGroupDates };
  const cycleKey = groupDateCycleKey(groupDates, modelVersion);
  const sameCycle = !force && oldKey === cycleKey;
  const groups = {};
  for (const group of V20_WORKER_GROUPS) {
    const prior = sameCycle ? old.groups?.[group] : null;
    const currentTotal = Math.max(0, Number(totals?.[group]) || 0);
    const progress = cleanProgress(group, groupDates[group], prior || {});
    if (currentTotal !== progress.total && progress.complete) {
      // Rows can become ready after a scan. Restart the keyset so late symbols
      // sorting below the old cursor are not permanently skipped.
      progress.cursor = "";
      progress.processed = 0;
      progress.complete = false;
      progress.scanPass += 1;
    }
    progress.total = currentTotal;
    groups[group] = progress;
  }
  const retryQueue = sameCycle ? dedupeRetries(old.retryQueue, groupDates) : [];
  const deadLetters = sameCycle
    ? (Array.isArray(old.deadLetters) ? old.deadLetters : []).filter((item) => {
      const group = text(item?.group_name);
      return V20_WORKER_GROUPS.includes(group) && text(item?.data_date) === groupDates[group];
    }).slice(-V20_ATTEMPT_LOG_LIMIT)
    : [];
  return {
    cycleKey,
    latestCycleKey: latestKey,
    modelVersion: text(modelVersion) || "20.0",
    groupDates,
    groups,
    retryQueue,
    deadLetters,
    attemptLog: sameCycle && Array.isArray(old.attemptLog)
      ? old.attemptLog.slice(-V20_ATTEMPT_LOG_LIMIT)
      : [],
    completed: sameCycle && old.completed === true,
    involvedDates: [...new Set([
      ...(sameCycle && Array.isArray(old.involvedDates) ? old.involvedDates.map(text) : []),
      ...Object.values(groupDates).map(text),
    ].filter(Boolean))].sort(),
  };
}

export function selectRetryTasks(queue, batchLimit, freshComplete = false) {
  const clean = Array.isArray(queue) ? queue : [];
  const limit = Math.max(1, Number(batchLimit) || 1);
  const allowance = freshComplete ? Math.min(limit, 10) : Math.min(10, Math.max(1, Math.floor(limit / 4)));
  return {
    selected: clean.slice(0, allowance),
    remaining: clean.slice(allowance),
  };
}

/**
 * Persists failed source rows in a bounded queue. A cursor may move past the
 * row only because its retry task is durable in stock_sync_state.details.
 */
export function settleWorkerAttempts({
  baseQueue = [],
  tasks = [],
  failureByKey = new Map(),
  deadLetters = [],
  attemptLog = [],
  at = new Date().toISOString(),
}) {
  const queue = [...(Array.isArray(baseQueue) ? baseQueue : [])];
  const dead = [...(Array.isArray(deadLetters) ? deadLetters : [])];
  const log = [...(Array.isArray(attemptLog) ? attemptLog : [])];
  for (const task of tasks) {
    const key = workerTaskKey(task);
    const error = text(failureByKey instanceof Map ? failureByKey.get(key) : failureByKey?.[key]);
    const priorAttempts = Math.max(0, Number(task?.attempts) || 0);
    const attemptNo = priorAttempts + 1;
    if (error) {
      const failed = {
        key,
        group_name: text(task.group_name),
        data_date: text(task.data_date),
        symbol: text(task.symbol),
        attempts: attemptNo,
        last_error: error.slice(0, 240),
        last_attempt_at: at,
      };
      log.push({ ...failed, outcome: attemptNo >= V20_MAX_ATTEMPTS ? "dead_letter" : "retry_queued" });
      if (attemptNo >= V20_MAX_ATTEMPTS) dead.push({ ...failed, terminal_at: at });
      else queue.push(failed);
    } else if (task?.fromRetry) {
      log.push({
        key,
        group_name: text(task.group_name),
        data_date: text(task.data_date),
        symbol: text(task.symbol),
        attempts: attemptNo,
        outcome: "retry_succeeded",
        last_attempt_at: at,
      });
    }
  }
  const groupDates = Object.fromEntries(V20_WORKER_GROUPS.map((group) => {
    const match = tasks.find((task) => text(task?.group_name) === group)
      || queue.find((task) => text(task?.group_name) === group)
      || dead.find((task) => text(task?.group_name) === group);
    return [group, text(match?.data_date)];
  }));
  // Dedupe without requiring all three dates; the caller owns cycle filtering.
  const byKey = new Map();
  for (const item of queue) {
    try {
      const normalized = {
        ...item,
        key: workerTaskKey(item),
        attempts: Math.max(0, Number(item.attempts) || 0),
      };
      const prior = byKey.get(normalized.key);
      if (!prior || normalized.attempts >= prior.attempts) byKey.set(normalized.key, normalized);
    } catch {}
  }
  return {
    retryQueue: [...byKey.values()].slice(0, V20_RETRY_QUEUE_LIMIT),
    deadLetters: dead.slice(-V20_ATTEMPT_LOG_LIMIT),
    attemptLog: log.slice(-V20_ATTEMPT_LOG_LIMIT),
    groupDates,
  };
}
