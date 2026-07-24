import { ApiError } from "./errors.ts";
import {
  evaluateSnapshotFreshness,
  type FreshnessPolicy,
} from "./freshness.ts";
import {
  mapMarket,
  mapPrediction,
  mapValidation,
  marketName,
  resolvePublicDataQuality,
} from "./mappers.ts";
import type {
  Decision,
  DecisionGateRow,
  DecisionPolicyStatus,
  JsonRecord,
  MarketScope,
  SecurityHistoryRow,
  SnapshotRows,
} from "./types.ts";

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
const RESEARCH_GATE_ENVELOPE_VERSIONS = new Set([
  "research-decision-gate.v1",
  "research-decision-gate.v2",
]);
const REQUIRED_EVIDENCE_CATEGORIES: Record<string, string> = {
  tradability_gate: "TRADABILITY",
  market_exposure_cap: "MARKET_EXPOSURE",
  position_capacity_limits: "POSITION_LIMITS",
};
const TRADABILITY_EVIDENCE_FIELDS = [
  "altered_trading_method_flag",
  "attention_flag",
  "disposal_flag",
  "full_cash_delivery_flag",
  "periodic_auction_flag",
  "suspended_flag",
  "trading_status",
];
const MARKET_EVIDENCE_FIELDS = [
  "calibrated_p_down",
  "calibrated_p_neutral",
  "calibrated_p_up",
  "forecast_market_volatility",
  "market_regime",
  "model_version",
  "training_end_date",
];
const POSITION_EVIDENCE_FIELDS = [
  "maximum_adv_participation",
  "maximum_industry_weight",
  "maximum_single_name_weight",
  "portfolio_policy_version",
  "portfolio_state_id",
  "proposed_adv_participation",
  "proposed_weight",
  "resulting_industry_weight",
];
const DECISIONS: Decision[] = ["CANDIDATE", "WATCH", "NO_TRADE"];
const POLICY_STATUSES: DecisionPolicyStatus[] = [
  "EVALUATED",
  "MISSING_REQUIRED_DATA",
  "VALIDATION_FAILED",
  "HARD_FAIL",
];

function validGateSourceDate(value: unknown, asOfDate: string): boolean {
  if (
    typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/u.test(value) ||
    Number.isNaN(Date.parse(`${value}T00:00:00Z`))
  ) return false;
  return new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value &&
    value <= asOfDate;
}

function isRecord(value: unknown): value is JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasExactFields(
  value: JsonRecord,
  expected: string[],
): boolean {
  const actual = Object.keys(value).sort();
  return actual.length === expected.length &&
    actual.every((field, index) => field === expected[index]);
}

function finiteInRange(
  value: unknown,
  minimum: number,
  maximum = Number.POSITIVE_INFINITY,
): value is number {
  return typeof value === "number" && Number.isFinite(value) &&
    value >= minimum && value <= maximum;
}

function validRequiredEvidenceDetails(
  category: string,
  evidence: JsonRecord,
  asOfDate: string,
): boolean {
  if (!isRecord(evidence.details)) return false;
  const details = evidence.details;
  if (category === "TRADABILITY") {
    if (
      !hasExactFields(details, TRADABILITY_EVIDENCE_FIELDS) ||
      typeof details.trading_status !== "string" ||
      details.trading_status.length === 0
    ) return false;
    const flags = [
      details.attention_flag,
      details.disposal_flag,
      details.altered_trading_method_flag,
      details.full_cash_delivery_flag,
      details.periodic_auction_flag,
      details.suspended_flag,
    ];
    if (flags.some((flag) => typeof flag !== "boolean")) return false;
    const expected = details.trading_status === "ACTIVE" &&
      details.disposal_flag === false &&
      details.altered_trading_method_flag === false &&
      details.full_cash_delivery_flag === false &&
      details.periodic_auction_flag === false &&
      details.suspended_flag === false;
    return typeof evidence.value === "boolean" && evidence.value === expected;
  }
  if (category === "MARKET_EXPOSURE") {
    if (
      !hasExactFields(details, MARKET_EVIDENCE_FIELDS) ||
      !finiteInRange(evidence.value, 0, 1) ||
      typeof details.market_regime !== "string" ||
      details.market_regime.length === 0 ||
      typeof details.model_version !== "string" ||
      details.model_version.length === 0 ||
      !finiteInRange(details.forecast_market_volatility, 0) ||
      typeof details.training_end_date !== "string" ||
      !validGateSourceDate(details.training_end_date, asOfDate) ||
      details.training_end_date >= asOfDate
    ) return false;
    const probabilities = [
      details.calibrated_p_up,
      details.calibrated_p_neutral,
      details.calibrated_p_down,
    ];
    return probabilities.every((value) => finiteInRange(value, 0, 1)) &&
      Math.abs(
          probabilities.reduce((sum, value) => sum + Number(value), 0) - 1,
        ) <= 0.000001;
  }
  if (category === "POSITION_LIMITS") {
    if (
      !hasExactFields(details, POSITION_EVIDENCE_FIELDS) ||
      typeof evidence.value !== "boolean" ||
      typeof details.portfolio_policy_version !== "string" ||
      details.portfolio_policy_version.length === 0 ||
      typeof details.portfolio_state_id !== "string" ||
      details.portfolio_state_id.length === 0
    ) return false;
    const limits = [
      details.maximum_single_name_weight,
      details.maximum_industry_weight,
      details.maximum_adv_participation,
      details.proposed_weight,
      details.resulting_industry_weight,
      details.proposed_adv_participation,
    ];
    if (!limits.every((value) => finiteInRange(value, 0, 1))) return false;
    const expected = Number(details.proposed_weight) <=
        Number(details.maximum_single_name_weight) &&
      Number(details.resulting_industry_weight) <=
        Number(details.maximum_industry_weight) &&
      Number(details.proposed_adv_participation) <=
        Number(details.maximum_adv_participation);
    return evidence.value === expected;
  }
  return false;
}

function hasCompletePolicyGateEvidence(
  prediction: JsonRecord,
  asOfDate: string,
  decisionAt: string,
): boolean {
  const gates = prediction.gates as JsonRecord[];
  return gates.length === GATE_ORDER.length &&
    gates.every((gate, index) =>
      gate.gate === GATE_ORDER[index] &&
      typeof gate.passed === "boolean" &&
      typeof gate.reason_code === "string" && gate.reason_code.length > 0 &&
      gate.actual !== null && gate.actual !== undefined &&
      gate.threshold !== null && gate.threshold !== undefined &&
      validGateSourceDate(gate.source_date, asOfDate) &&
      hasRequiredEvidence(
        gate,
        prediction,
        asOfDate,
        decisionAt,
      )
    );
}

function hasRequiredEvidence(
  gate: JsonRecord,
  prediction: JsonRecord,
  asOfDate: string,
  decisionAt: string,
): boolean {
  const expectedCategory = REQUIRED_EVIDENCE_CATEGORIES[String(gate.gate)];
  if (!expectedCategory) return true;
  const evidence = gate.evidence;
  if (!isRecord(evidence)) return false;
  const availableAt = typeof evidence.available_at === "string" &&
      /(?:Z|[+-]\d{2}:\d{2})$/u.test(evidence.available_at)
    ? Date.parse(evidence.available_at)
    : Number.NaN;
  const decisionTime = Date.parse(decisionAt);
  const expectedMarket = prediction.market === "LISTED" ? "TWSE" : "TPEX";
  const expectedSymbol = expectedCategory === "MARKET_EXPOSURE"
    ? null
    : prediction.symbol;
  return evidence.contract_version ===
      "decision-policy-required-evidence.v1" &&
    evidence.category === expectedCategory &&
    evidence.status === "AVAILABLE" &&
    evidence.validation_result === "PASS" &&
    evidence.reason_code === "PASS" &&
    evidence.market === expectedMarket &&
    evidence.symbol === expectedSymbol &&
    evidence.effective_date === asOfDate &&
    gate.source_date === evidence.effective_date &&
    Number.isFinite(availableAt) &&
    Number.isFinite(decisionTime) &&
    availableAt <= decisionTime &&
    typeof evidence.source === "string" && evidence.source.length > 0 &&
    typeof evidence.publication_id === "string" &&
    evidence.publication_id.length > 0 &&
    evidence.value === gate.actual &&
    validRequiredEvidenceDetails(expectedCategory, evidence, asOfDate) &&
    requiredEvidenceMatchesPrediction(expectedCategory, evidence, prediction);
}

function requiredEvidenceMatchesPrediction(
  category: string,
  evidence: JsonRecord,
  prediction: JsonRecord,
): boolean {
  if (!isRecord(evidence.details)) return false;
  if (category === "MARKET_EXPOSURE") {
    return evidence.value === prediction.market_exposure_cap &&
      evidence.details.market_regime === prediction.market_regime;
  }
  if (category === "POSITION_LIMITS") {
    return evidence.details.maximum_single_name_weight ===
        prediction.max_single_position &&
      evidence.details.maximum_industry_weight ===
        prediction.max_industry_position;
  }
  return true;
}

function hasInvalidAvailableEvidence(
  prediction: JsonRecord,
  asOfDate: string,
  decisionAt: string,
): boolean {
  if (!Array.isArray(prediction.gates)) return false;
  return prediction.gates.some((gate) => {
    if (!isRecord(gate)) return false;
    const category = REQUIRED_EVIDENCE_CATEGORIES[String(gate.gate)];
    return category !== undefined &&
      isRecord(gate.evidence) &&
      gate.evidence.status === "AVAILABLE" &&
      !hasRequiredEvidence(gate, prediction, asOfDate, decisionAt);
  });
}

function actionMatchesPolicyGates(prediction: JsonRecord): boolean {
  const gates = prediction.gates as JsonRecord[];
  const allGatesPassed = gates.every((gate) => gate.passed === true);
  if (prediction.decision === "CANDIDATE") return allGatesPassed;
  if (prediction.decision === "WATCH") {
    return allGatesPassed &&
      Array.isArray(prediction.reason_codes) &&
      prediction.reason_codes.includes("OUTSIDE_TOP_K");
  }
  return prediction.decision === "NO_TRADE" && !allGatesPassed;
}

function emptySnapshot(marketScope: MarketScope): JsonRecord {
  return {
    api_contract_version: API_CONTRACT_VERSION,
    as_of_date: null,
    decision_at: null,
    horizon: 5,
    market_scope: marketScope,
    system_status: "RESEARCH_ONLY",
    stale: true,
    freshness: {
      method: "NO_SNAPSHOT",
      calendar_status: "UNAVAILABLE",
      snapshot_session_date: null,
      expected_session_date: null,
    },
    data_quality_hard_fail: false,
    reason_codes: ["NO_PREDICTION_SNAPSHOT"],
    market: null,
    decision_counts: {
      CANDIDATE: 0,
      WATCH: 0,
      NO_TRADE: 0,
      MISSING_REQUIRED_DATA: 0,
      VALIDATION_FAILED: 0,
      HARD_FAIL: 0,
    },
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
    typeof expectedContract !== "string" ||
    !RESEARCH_GATE_ENVELOPE_VERSIONS.has(expectedContract) ||
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
        return actual.contract_version === expectedContract &&
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
  marketScope: MarketScope,
): boolean {
  if (
    !rows.validationRun ||
    rows.validationRun.validation_status !== "PASS" ||
    !rows.validationRun.locked_holdout ||
    rows.run.hard_fail_count > 0 ||
    !rows.markets.some((market) => market.market === marketScope) ||
    mapped.length === 0
  ) return false;
  return mapped.every((prediction) => {
    return hasCompletePolicyGateEvidence(
      prediction,
      rows.run.as_of_date,
      rows.run.decision_at,
    ) &&
      prediction.data_quality_status === "PASS" &&
      prediction.decision_policy_status === "EVALUATED" &&
      DECISIONS.includes(prediction.decision as Decision) &&
      actionMatchesPolicyGates(prediction);
  });
}

function validateManifest(rows: SnapshotRows): void {
  const run = rows.run;
  const policyManifest = [
    run.policy_input_missing_count ?? null,
    run.policy_validation_failed_count ?? null,
    run.policy_hard_fail_count ?? null,
  ];
  const hasPolicyManifest = policyManifest.some((value) => value !== null);
  const validPolicyManifest = policyManifest.every((value) =>
    typeof value === "number" && Number.isInteger(value) && value >= 0
  );
  if (hasPolicyManifest && !validPolicyManifest) {
    throw new ApiError(
      409,
      "PREDICTION_POLICY_MANIFEST_INVALID",
      "Prediction policy status manifest is incomplete",
    );
  }
  const expected = run.candidate_count + run.watch_count + run.no_trade_count +
    (hasPolicyManifest
      ? (run.policy_input_missing_count ?? 0) +
        (run.policy_validation_failed_count ?? 0) +
        (run.policy_hard_fail_count ?? 0)
      : 0);
  if (rows.predictions.length !== expected) {
    throw new ApiError(
      409,
      "PREDICTION_SNAPSHOT_INCOMPLETE",
      "Prediction row count does not match the run manifest",
    );
  }
  const rawDecisionCounts: Record<Decision, number> = {
    CANDIDATE: 0,
    WATCH: 0,
    NO_TRADE: 0,
  };
  const rawPolicyCounts: Record<DecisionPolicyStatus, number> = {
    EVALUATED: 0,
    MISSING_REQUIRED_DATA: 0,
    VALIDATION_FAILED: 0,
    HARD_FAIL: 0,
  };
  for (const prediction of rows.predictions) {
    const policyStatus = prediction.decision_policy_status ?? null;
    if (
      prediction.decision !== null &&
      !DECISIONS.includes(prediction.decision)
    ) {
      throw new ApiError(
        409,
        "PREDICTION_DECISION_CONTRACT_INVALID",
        "Prediction contains an unsupported decision action",
      );
    }
    if (
      policyStatus !== null &&
      !POLICY_STATUSES.includes(policyStatus)
    ) {
      if (hasPolicyManifest) {
        throw new ApiError(
          409,
          "PREDICTION_POLICY_CONTRACT_INVALID",
          "Prediction contains an unsupported policy status",
        );
      }
      continue;
    }
    if (prediction.decision !== null) {
      rawDecisionCounts[prediction.decision] += 1;
    }
    if (policyStatus !== null) {
      rawPolicyCounts[policyStatus] += 1;
    }
  }
  if (
    rawDecisionCounts.CANDIDATE !== run.candidate_count ||
    rawDecisionCounts.WATCH !== run.watch_count ||
    rawDecisionCounts.NO_TRADE !== run.no_trade_count
  ) {
    throw new ApiError(
      409,
      "PREDICTION_DECISION_COUNT_MISMATCH",
      "Prediction decision counts do not match the run manifest",
    );
  }
  if (!hasPolicyManifest) {
    return;
  }
  if (
    rawPolicyCounts.EVALUATED !==
      run.candidate_count + run.watch_count + run.no_trade_count ||
    rawPolicyCounts.MISSING_REQUIRED_DATA !== run.policy_input_missing_count ||
    rawPolicyCounts.VALIDATION_FAILED !== run.policy_validation_failed_count ||
    rawPolicyCounts.HARD_FAIL !== run.policy_hard_fail_count ||
    rows.predictions.some((prediction) =>
      (prediction.decision_policy_status ?? null) === "EVALUATED"
        ? prediction.decision === null
        : prediction.decision !== null
    )
  ) {
    throw new ApiError(
      409,
      "PREDICTION_POLICY_COUNT_MISMATCH",
      "Prediction policy status counts do not match the run manifest",
    );
  }
}

function assertMarketIsolation(
  rows: SnapshotRows,
  marketScope: MarketScope,
): void {
  const runMarketScope = rows.run.market_scope ?? "TWSE";
  const mixed = runMarketScope !== marketScope ||
    rows.predictions.some((prediction) => prediction.market !== marketScope) ||
    rows.securities.some((security) => security.market !== marketScope) ||
    rows.markets.some((market) => market.market !== marketScope) ||
    rows.calendarObservations.some((row) => row.market !== marketScope);
  if (mixed) {
    throw new ApiError(
      409,
      "PREDICTION_MARKET_SCOPE_MISMATCH",
      "Prediction snapshot contains data from another market",
    );
  }
}

export function buildSnapshot(
  rows: SnapshotRows | null,
  marketScope: MarketScope,
  now = new Date(),
  freshnessPolicy: FreshnessPolicy = {},
): JsonRecord {
  if (!rows) return emptySnapshot(marketScope);
  assertMarketIsolation(rows, marketScope);
  validateManifest(rows);

  const securities = new Map(
    rows.securities.map((row) => [row.security_id, row]),
  );
  const currentSecurityHistory = new Map<number, SecurityHistoryRow>();
  const taipeiDate = new Date(now.getTime() + 8 * 3_600_000)
    .toISOString().slice(0, 10);
  for (const row of rows.currentSecurityHistory) {
    const availableAt = Date.parse(row.available_at);
    const activeOnTaipeiDate = row.effective_from <= taipeiDate &&
      (row.effective_to === null || taipeiDate < row.effective_to);
    if (
      activeOnTaipeiDate &&
      Number.isFinite(availableAt) &&
      availableAt <= now.getTime() &&
      !currentSecurityHistory.has(row.security_id)
    ) {
      currentSecurityHistory.set(row.security_id, row);
    }
  }
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
      currentSecurityHistory.get(prediction.security_id),
      audits.get(prediction.security_id),
      gates.get(prediction.stock_prediction_id) ?? [],
    );
  });
  if (
    mapped.some((prediction) =>
      (prediction.decision_policy_status === "HARD_FAIL") !==
        (prediction.data_quality_status === "HARD_FAIL")
    )
  ) {
    throw new ApiError(
      409,
      "PREDICTION_HARD_FAIL_STATUS_MISMATCH",
      "HARD_FAIL policy status and data quality must agree",
    );
  }
  if (
    mapped.some((prediction) =>
      hasInvalidAvailableEvidence(
        prediction,
        rows.run.as_of_date,
        rows.run.decision_at,
      ) ||
      (
        prediction.decision_policy_status === "EVALUATED" &&
        (
          prediction.data_quality_status !== "PASS" ||
          !hasCompletePolicyGateEvidence(
            prediction,
            rows.run.as_of_date,
            rows.run.decision_at,
          ) ||
          !actionMatchesPolicyGates(prediction)
        )
      )
    )
  ) {
    throw new ApiError(
      409,
      "PREDICTION_POLICY_EVIDENCE_INVALID",
      "Evaluated Decision Policy action lacks complete consistent evidence",
    );
  }
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
    data_quality_status: "HARD_FAIL",
    data_quality_hard_fail: true,
    decision: null,
    decision_policy_status: "HARD_FAIL",
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
      data_quality_status: "HARD_FAIL",
      data_quality_hard_fail: true,
      decision: null,
      decision_policy_status: "HARD_FAIL",
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
  const formalReady = formalContractReady(mapped, rows, marketScope);
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
  const market = mapMarket(rows.run, rows.markets, marketScope);
  if (market === null) reasonCodes.add("MARKET_POLICY_DATA_UNAVAILABLE");
  if (!included.length) reasonCodes.add("NO_ELIGIBLE_PREDICTIONS");
  const freshness = evaluateSnapshotFreshness(
    rows.run,
    rows.calendarObservations,
    now,
    freshnessPolicy,
  );
  for (const reasonCode of freshness.reasonCodes) reasonCodes.add(reasonCode);
  const publishedDecisionCounts = {
    CANDIDATE: 0,
    WATCH: 0,
    NO_TRADE: 0,
    MISSING_REQUIRED_DATA: 0,
    VALIDATION_FAILED: 0,
    HARD_FAIL: 0,
  };
  for (const prediction of [...included, ...excluded]) {
    const status = prediction.decision_policy_status;
    const decision = prediction.decision;
    if (status === "EVALUATED" && typeof decision === "string") {
      publishedDecisionCounts[decision as Decision] += 1;
    } else if (
      typeof status === "string" &&
      POLICY_STATUSES.includes(status as DecisionPolicyStatus)
    ) {
      publishedDecisionCounts[status as keyof typeof publishedDecisionCounts] +=
        1;
    }
  }

  return {
    api_contract_version: API_CONTRACT_VERSION,
    as_of_date: rows.run.as_of_date,
    decision_at: rows.run.decision_at,
    horizon: rows.run.horizon,
    market_scope: marketScope,
    system_status: systemStatus,
    stale: freshness.stale,
    freshness: freshness.metadata,
    data_quality_hard_fail: false,
    reason_codes: [...reasonCodes],
    market,
    decision_counts: publishedDecisionCounts,
    predictions: included,
    watchlist: [],
    excluded,
    model_version: rows.run.model_bundle_version,
    training_end_date: rows.run.training_end_date,
    cost_profile_version: rows.run.cost_profile_version,
    validation: mapValidation(rows),
  };
}
