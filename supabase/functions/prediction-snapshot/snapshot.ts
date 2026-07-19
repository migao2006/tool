import { ApiError } from "./errors.ts";
import {
  mapMarket,
  mapPrediction,
  mapValidation,
  marketName,
} from "./mappers.ts";
import type { DecisionGateRow, JsonRecord, SnapshotRows } from "./types.ts";

export const API_CONTRACT_VERSION = "prediction-snapshot.v1";
const GATE_ORDER = [
  "data_quality_hard_gate",
  "tradability_gate",
  "liquidity_capacity_gate",
  "market_exposure_cap",
  "calibrated_direction_probabilities",
  "net_quantile_thresholds",
  "rank_eligibility",
  "position_capacity_limits",
];

function emptySnapshot(): JsonRecord {
  return {
    api_contract_version: API_CONTRACT_VERSION,
    as_of_date: null,
    decision_at: null,
    horizon: 5,
    system_status: "RESEARCH_ONLY",
    stale: true,
    data_quality_hard_fail: false,
    reason_codes: ["NO_PREDICTION_SNAPSHOT"],
    market: null,
    predictions: [],
    watchlist: [],
    excluded: [],
    model_version: null,
    training_end_date: null,
    cost_profile_version: null,
    validation: {},
  };
}

function formalContractReady(
  mapped: JsonRecord[],
  rows: SnapshotRows,
): boolean {
  if (
    !rows.validationRun ||
    rows.validationRun.validation_status !== "PASS" ||
    !rows.validationRun.locked_holdout ||
    rows.run.hard_fail_count > 0 ||
    !rows.markets.some((market) => market.market === "TWSE") ||
    !rows.markets.some((market) => market.market === "TPEX")
  ) return false;
  return mapped.every((prediction) => {
    const gates = prediction.gates as JsonRecord[];
    return gates.length === GATE_ORDER.length &&
      gates.every((gate, index) =>
        gate.gate === GATE_ORDER[index] && typeof gate.source_date === "string"
      );
  });
}

export function buildSnapshot(
  rows: SnapshotRows | null,
  now = new Date(),
  staleHours = 72,
): JsonRecord {
  if (!rows) return emptySnapshot();
  const expected = rows.run.candidate_count + rows.run.watch_count +
    rows.run.no_trade_count;
  if (rows.predictions.length !== expected) {
    throw new ApiError(
      409,
      "PREDICTION_SNAPSHOT_INCOMPLETE",
      "Prediction row count does not match the run manifest",
    );
  }
  const decisionCounts = rows.predictions.reduce(
    (counts, prediction) => {
      counts[prediction.decision] += 1;
      return counts;
    },
    { CANDIDATE: 0, WATCH: 0, NO_TRADE: 0 },
  );
  if (
    decisionCounts.CANDIDATE !== rows.run.candidate_count ||
    decisionCounts.WATCH !== rows.run.watch_count ||
    decisionCounts.NO_TRADE !== rows.run.no_trade_count
  ) {
    throw new ApiError(
      409,
      "PREDICTION_DECISION_COUNT_MISMATCH",
      "Prediction decision counts do not match the run manifest",
    );
  }

  const securities = new Map(
    rows.securities.map((row) => [row.security_id, row]),
  );
  const audits = new Map(rows.audits.map((row) => [row.security_id, row]));
  const gates = new Map<number, DecisionGateRow[]>();
  for (const gate of rows.gates) {
    gates.set(gate.stock_prediction_id, [
      ...(gates.get(gate.stock_prediction_id) ?? []),
      gate,
    ]);
  }

  const mapped = rows.predictions.map((prediction) => {
    const security = securities.get(prediction.security_id);
    if (!security || security.asset_type !== "COMMON_STOCK") {
      throw new ApiError(
        409,
        "PREDICTION_SECURITY_IDENTITY_MISSING",
        "Prediction security identity is missing or unsupported",
      );
    }
    return mapPrediction(
      rows.run,
      prediction,
      security,
      audits.get(prediction.security_id),
      gates.get(prediction.stock_prediction_id) ?? [],
    );
  });
  const included = mapped.filter((prediction) =>
    prediction.data_quality_hard_fail !== true
  );
  const excludedFromPredictions = mapped.filter((prediction) =>
    prediction.data_quality_hard_fail === true
  ).map((prediction) => ({
    as_of_date: prediction.as_of_date,
    symbol: prediction.symbol,
    name: prediction.name,
    market: prediction.market,
    asset_type: prediction.asset_type,
    horizon: prediction.horizon,
    data_quality_status: "FAIL",
    data_quality_hard_fail: true,
    decision: "NO_TRADE",
    reason_codes: prediction.reason_codes,
    latest_available_at: prediction.latest_available_at,
  }));
  const excludedSecurityIds = new Set(
    rows.predictions.filter((prediction) => {
      const audit = audits.get(prediction.security_id);
      return audit?.hard_fail ?? prediction.data_quality_status === "FAIL";
    }).map((prediction) => prediction.security_id),
  );
  const auditOnlyExcluded = rows.audits.filter((audit) =>
    audit.hard_fail && !excludedSecurityIds.has(audit.security_id)
  ).map((audit) => {
    const security = securities.get(audit.security_id);
    if (!security || security.asset_type !== "COMMON_STOCK") {
      throw new ApiError(
        409,
        "PREDICTION_SECURITY_IDENTITY_MISSING",
        "Excluded security identity is missing or unsupported",
      );
    }
    excludedSecurityIds.add(audit.security_id);
    return {
      as_of_date: rows.run.as_of_date,
      symbol: security.symbol,
      name: security.display_name,
      market: marketName(security.market),
      asset_type: "STOCK",
      horizon: rows.run.horizon,
      data_quality_status: "FAIL",
      data_quality_hard_fail: true,
      decision: "NO_TRADE",
      reason_codes: audit.reason_codes.length
        ? audit.reason_codes
        : ["DATA_QUALITY_HARD_FAIL"],
      latest_available_at: audit.latest_available_at ??
        rows.run.latest_available_at,
    };
  });
  const excluded = [...excludedFromPredictions, ...auditOnlyExcluded];
  if (excludedSecurityIds.size !== rows.run.hard_fail_count) {
    throw new ApiError(
      409,
      "PREDICTION_HARD_FAIL_COUNT_MISMATCH",
      "Excluded security count does not match the run manifest",
    );
  }
  const formalReady = formalContractReady(mapped, rows);
  const sourceStatus = rows.run.system_validation_status;
  const systemStatus = sourceStatus === "PASS" && !formalReady
    ? "RESEARCH_ONLY"
    : sourceStatus;
  const reasonCodes = new Set<string>();
  if (systemStatus === "RESEARCH_ONLY") reasonCodes.add("RESEARCH_ONLY");
  if (sourceStatus === "PASS" && !formalReady) {
    reasonCodes.add("FORMAL_SNAPSHOT_CONTRACT_INCOMPLETE");
  }
  if (rows.validationLinkStatus !== "LINKED") {
    reasonCodes.add("VALIDATION_SNAPSHOT_NOT_LINKED");
  }
  if (!included.length) reasonCodes.add("NO_ELIGIBLE_PREDICTIONS");
  const latestAvailable = Date.parse(rows.run.latest_available_at);
  const stale = !Number.isFinite(latestAvailable) ||
    now.getTime() - latestAvailable > staleHours * 3_600_000;
  if (stale) reasonCodes.add("STALE_PREDICTION_SNAPSHOT");

  return {
    api_contract_version: API_CONTRACT_VERSION,
    as_of_date: rows.run.as_of_date,
    decision_at: rows.run.decision_at,
    horizon: rows.run.horizon,
    system_status: systemStatus,
    stale,
    data_quality_hard_fail: false,
    reason_codes: [...reasonCodes],
    market: mapMarket(rows.run, rows.markets),
    predictions: included,
    watchlist: [],
    excluded,
    model_version: rows.run.model_bundle_version,
    training_end_date: rows.run.training_end_date,
    cost_profile_version: rows.run.cost_profile_version,
    validation: mapValidation(rows),
  };
}
