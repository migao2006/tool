import { ApiError } from "./errors.ts";
import {
  mapMarket,
  mapPrediction,
  mapValidation,
  marketName,
  resolvePublicDataQuality,
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
const RESEARCH_GATE_ENVELOPE_VERSION = "research-decision-gate.v1";

function validGateSourceDate(value: unknown, asOfDate: string): boolean {
  if (
    typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/u.test(value) ||
    Number.isNaN(Date.parse(`${value}T00:00:00Z`))
  ) return false;
  return new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value &&
    value <= asOfDate;
}

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

function validateResearchGateAttachments(
  rows: SnapshotRows,
  gatesByPrediction: Map<number, DecisionGateRow[]>,
): void {
  if (!Object.hasOwn(rows.run.source_dates, "decision_gate_count")) return;
  const expectedCount = rows.run.source_dates.decision_gate_count;
  const expectedContract =
    rows.run.source_dates.decision_gate_attachment_contract;
  const snapshotSha256 = rows.run.source_dates.snapshot_sha256;
  if (
    typeof expectedCount !== "number" || !Number.isInteger(expectedCount) ||
    expectedCount < 0 ||
    expectedContract !== RESEARCH_GATE_ENVELOPE_VERSION ||
    typeof snapshotSha256 !== "string"
  ) {
    throw new ApiError(
      409,
      "RESEARCH_DECISION_GATE_MANIFEST_INVALID",
      "Research decision gate manifest is invalid",
    );
  }
  if (expectedCount === 0) {
    if (rows.gates.length !== 0) {
      throw new ApiError(
        409,
        "RESEARCH_DECISION_GATE_ATTACHMENT_MISMATCH",
        "Legacy research run unexpectedly contains decision gate rows",
      );
    }
    return;
  }
  if (
    rows.gates.length !== expectedCount ||
    expectedCount !== rows.predictions.length * GATE_ORDER.length
  ) {
    throw new ApiError(
      409,
      "RESEARCH_DECISION_GATE_ATTACHMENT_INCOMPLETE",
      "Research decision gate rows do not match the run manifest",
    );
  }
  for (const prediction of rows.predictions) {
    const gates = [
      ...(gatesByPrediction.get(prediction.stock_prediction_id) ?? []),
    ]
      .sort((left, right) => left.gate_order - right.gate_order);
    const valid = gates.length === GATE_ORDER.length &&
      gates.every((gate, index) => {
        const actual = gate.actual_value;
        if (
          gate.gate_name !== GATE_ORDER[index] || actual === null ||
          typeof actual !== "object" || Array.isArray(actual)
        ) return false;
        return actual.contract_version === RESEARCH_GATE_ENVELOPE_VERSION &&
          actual.attachment_snapshot_sha256 === snapshotSha256 &&
          Object.hasOwn(actual, "value");
      });
    if (!valid) {
      throw new ApiError(
        409,
        "RESEARCH_DECISION_GATE_ATTACHMENT_MISMATCH",
        "Research decision gate attachment does not match the prediction snapshot",
      );
    }
  }
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
    const complete = gates.length === GATE_ORDER.length &&
      gates.every((gate, index) =>
        gate.gate === GATE_ORDER[index] &&
        typeof gate.passed === "boolean" &&
        typeof gate.reason_code === "string" && gate.reason_code.length > 0 &&
        gate.actual !== null && gate.actual !== undefined &&
        gate.threshold !== null && gate.threshold !== undefined &&
        validGateSourceDate(gate.source_date, rows.run.as_of_date)
      );
    return complete && (prediction.decision !== "CANDIDATE" ||
      gates.every((gate) => gate.passed === true));
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
  validateResearchGateAttachments(rows, gates);

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
      return resolvePublicDataQuality(rows.run, prediction, audit).hardFail;
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
