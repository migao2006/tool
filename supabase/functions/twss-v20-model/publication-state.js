export const V20_PUBLICATION_GROUPS = Object.freeze(["listed", "otc", "etf"]);

const text = (value) => String(value ?? "").trim();
const isoDate = (value) => /^\d{4}-\d{2}-\d{2}/.test(text(value))
  ? text(value).slice(0, 10)
  : "";

export function completionDate(value) {
  return isoDate(text(value).split(":", 1)[0]);
}

/**
 * The v20 model may only consume a single point-in-time source cycle.  The
 * universe establishes that date and every deep worker must explicitly mark
 * the same date complete.  A newer row in one cache group is never enough to
 * advance public output on its own.
 * @param {{ universe?: any, deepStates?: Record<string, any> }} [input]
 */
export function resolveReadySourceCycle(input = {}) {
  const { universe, deepStates = {} } = input;
  const universeDetails = universe?.details && typeof universe.details === "object"
    ? universe.details
    : {};
  const fallbackDate = isoDate(universe?.cycle_date);
  const sourceDates = Object.fromEntries(V20_PUBLICATION_GROUPS.map((group) => [
    group,
    isoDate(universeDetails?.groupDates?.[group]) || fallbackDate,
  ]));
  const missingSourceGroups = V20_PUBLICATION_GROUPS.filter((group) => !sourceDates[group]);
  if (universe?.status !== "success" || missingSourceGroups.length) {
    return {
      ready: false,
      reason: "universe_source_not_ready",
      sourceDate: null,
      sourceDates,
      missingGroups: missingSourceGroups,
      completionKeys: {},
    };
  }

  const uniqueDates = [...new Set(Object.values(sourceDates))];
  if (uniqueDates.length !== 1 || (fallbackDate && fallbackDate !== uniqueDates[0])) {
    return {
      ready: false,
      reason: "source_dates_not_aligned",
      sourceDate: null,
      sourceDates,
      missingGroups: [],
      completionKeys: {},
    };
  }

  const sourceDate = uniqueDates[0];
  const completionKeys = {};
  const incompleteGroups = [];
  for (const group of V20_PUBLICATION_GROUPS) {
    const state = deepStates[group] || deepStates[`deep_${group}`] || null;
    const details = state?.details && typeof state.details === "object" ? state.details : {};
    const key = text(details.completedCycleKey);
    completionKeys[group] = key;
    const stateDate = isoDate(state?.cycle_date);
    if (stateDate !== sourceDate || completionDate(key) !== sourceDate) incompleteGroups.push(group);
  }
  if (incompleteGroups.length) {
    return {
      ready: false,
      reason: "source_groups_incomplete",
      sourceDate,
      sourceDates,
      missingGroups: incompleteGroups,
      completionKeys,
    };
  }

  return {
    ready: true,
    reason: "ready",
    sourceDate,
    sourceDates,
    missingGroups: [],
    completionKeys,
  };
}

export function normalizeEnrichmentSummary(value = {}) {
  const number = (input) => Math.max(0, Number(input) || 0);
  const total = number(value?.total);
  const pending = number(value?.pending);
  const running = number(value?.running);
  const retryableErrors = number(value?.retryableErrors ?? value?.retryable_errors);
  const terminalErrors = number(value?.terminalErrors ?? value?.terminal_errors);
  const unresolved = number(value?.unresolved || pending + running + retryableErrors);
  return {
    total,
    pending,
    running,
    success: number(value?.success),
    error: number(value?.error),
    retryableErrors,
    terminalErrors,
    unresolved,
    complete: value?.complete === true,
    available: value?.available !== false && (total > 0 || value?.complete === true),
  };
}

export function enrichmentFingerprint(value = {}) {
  const summary = normalizeEnrichmentSummary(value);
  return [
    summary.total,
    summary.pending,
    summary.running,
    summary.success,
    summary.retryableErrors,
    summary.terminalErrors,
    summary.unresolved,
    summary.complete ? 1 : 0,
  ].join(":");
}

export function publicationPhaseFor(summary = {}) {
  const normalized = normalizeEnrichmentSummary(summary);
  if (!normalized.available) return "base_ready";
  if (normalized.complete && normalized.unresolved === 0) return "complete";
  return "enriching";
}

export function publicationProgressStatus({
  hasError = false,
  publicationSucceeded = false,
  awaitingInitialPublication = false,
  fallbackStatus = "success",
} = {}) {
  if (hasError) return "partial";
  if (publicationSucceeded) return "success";
  if (awaitingInitialPublication) return "running";
  return text(fallbackStatus) || "success";
}

export function finalizePublicationState({
  state = {},
  priorDetails = {},
  sourceDate = "",
  sourceKey = "",
  enrichment = {},
  publication = {},
  publishedAt = "",
  dataCompleteness = 0,
} = {}) {
  const finalSourceDate = isoDate(sourceDate);
  const finalSourceKey = text(sourceKey);
  const finalPublishedAt = text(publishedAt);
  if (!finalSourceDate || !finalSourceKey || !finalPublishedAt) {
    throw new Error("v20_finalized_publication_state_invalid");
  }
  const normalizedEnrichment = normalizeEnrichmentSummary(enrichment);
  const publicationPhase = publicationPhaseFor(normalizedEnrichment);
  const samePublishedDate = isoDate(priorDetails?.publishedDataDate) === finalSourceDate;
  const workerCycle = priorDetails?.workerCycle && typeof priorDetails.workerCycle === "object"
    ? { ...priorDetails.workerCycle, completed: true }
    : priorDetails?.workerCycle;
  return {
    statePatch: {
      last_success_at: finalPublishedAt,
      next_run_at: null,
      last_symbol: null,
      cycle_number: Math.max(0, Math.trunc(Number(state?.cycle_number) || 0)) + 1,
    },
    details: {
      ...priorDetails,
      workerCycle,
      scoredCycleKey: finalSourceKey,
      scoredCycleAt: priorDetails?.scoredCycleAt || finalPublishedAt,
      completedCycleKey: finalSourceKey,
      completedCycleStatus: "success",
      completedCycleAt: samePublishedDate && priorDetails?.completedCycleAt
        ? priorDetails.completedCycleAt
        : finalPublishedAt,
      publishedCycleKey: finalSourceKey,
      publishedDataDate: finalSourceDate,
      publicationPhase,
      baseCompletedAt: samePublishedDate && priorDetails?.baseCompletedAt
        ? priorDetails.baseCompletedAt
        : finalPublishedAt,
      enrichmentCompletedAt: publicationPhase === "complete"
        ? samePublishedDate && priorDetails?.enrichmentCompletedAt
          ? priorDetails.enrichmentCompletedAt
          : finalPublishedAt
        : null,
      enrichmentPending: normalizedEnrichment.unresolved,
      enrichmentFingerprint: enrichmentFingerprint(normalizedEnrichment),
      sourceDates: priorDetails?.targetSourceDates || priorDetails?.sourceDates || {},
      dataCompleteness: Number(dataCompleteness) || 0,
      publishedAt: finalPublishedAt,
      publicationRunId: publication?.runId || null,
      publicationKey: publication?.publicationKey || null,
      contentHash: publication?.contentHash || null,
    },
  };
}

/**
 * Full-market scoring is keyed only by point-in-time source data and model
 * code. A cycle that has finished scoring but is still draining coalesced
 * dirty work must continue through the incremental path; re-running the full
 * scan would never settle the queue and therefore could never publish.
 */
export function shouldRunFullMarket({
  force = false,
  completedCycleKey = "",
  scoredCycleKey = "",
  sourceKey = "",
} = {}) {
  if (force === true || !sourceKey) return true;
  return ![completedCycleKey, scoredCycleKey]
    .map((value) => String(value || ""))
    .includes(String(sourceKey));
}
