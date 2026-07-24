export const DECISION_ACTIONS = Object.freeze([
  "CANDIDATE",
  "WATCH",
  "NO_TRADE",
]);

export const DECISION_POLICY_STATUSES = Object.freeze([
  "EVALUATED",
  "MISSING_REQUIRED_DATA",
  "VALIDATION_FAILED",
  "HARD_FAIL",
]);

const ACTION_SET = new Set(DECISION_ACTIONS);
const STATUS_SET = new Set(DECISION_POLICY_STATUSES);
const ACTION_LABELS = Object.freeze({
  CANDIDATE: "正式候選",
  WATCH: "觀察",
  NO_TRADE: "政策不進場",
});
const STATUS_LABELS = Object.freeze({
  EVALUATED: "政策已評估",
  MISSING_REQUIRED_DATA: "政策資料未完整",
  VALIDATION_FAILED: "政策驗證未通過",
  HARD_FAIL: "資料硬性失敗",
});

function normalizedValue(value) {
  return value === null || value === undefined
    ? null
    : String(value).trim().toUpperCase() || null;
}

function missingPolicyReason(reason) {
  const normalized = normalizedValue(reason) ?? "";
  return normalized === "RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY" ||
    normalized === "REQUIRED_DECISION_POLICY_DATA_MISSING" ||
    normalized.endsWith("_INPUT_MISSING") ||
    normalized.includes("SOURCE_DATE_MISSING");
}

export function normalizeDecisionPolicy({
  decision,
  status,
  reasonCodes = [],
  gates = [],
  hardFail = false,
  systemStatus = null,
} = {}) {
  if (hardFail) {
    return Object.freeze({ decision: null, status: "HARD_FAIL" });
  }
  const normalizedDecision = normalizedValue(decision);
  const normalizedStatus = normalizedValue(status);
  if (STATUS_SET.has(normalizedStatus)) {
    if (
      normalizedStatus === "EVALUATED" &&
      ACTION_SET.has(normalizedDecision)
    ) {
      return Object.freeze({
        decision: normalizedDecision,
        status: normalizedStatus,
      });
    }
    if (normalizedStatus !== "EVALUATED" && normalizedDecision === null) {
      return Object.freeze({ decision: null, status: normalizedStatus });
    }
    return Object.freeze({ decision: null, status: "VALIDATION_FAILED" });
  }
  if (normalizedStatus !== null) {
    return Object.freeze({ decision: null, status: "VALIDATION_FAILED" });
  }

  const gateReasons = gates.map((gate) =>
    gate?.reason_code ?? gate?.reasonCode ?? null
  );
  if (
    [...reasonCodes, ...gateReasons].some(missingPolicyReason)
  ) {
    return Object.freeze({
      decision: null,
      status: "MISSING_REQUIRED_DATA",
    });
  }
  if (normalizedValue(systemStatus) === "RESEARCH_ONLY") {
    return Object.freeze({
      decision: null,
      status: "VALIDATION_FAILED",
    });
  }
  if (ACTION_SET.has(normalizedDecision)) {
    return Object.freeze({
      decision: normalizedDecision,
      status: "EVALUATED",
    });
  }
  return Object.freeze({ decision: null, status: "VALIDATION_FAILED" });
}

export function decisionCategory(record) {
  return record?.decision_policy_status === "EVALUATED"
    ? record.decision
    : record?.decision_policy_status ?? null;
}

export function decisionActionLabel(value) {
  return ACTION_LABELS[value] ?? value ?? "—";
}

export function decisionPolicyStatusLabel(value) {
  return STATUS_LABELS[value] ?? value ?? "—";
}

export function decisionPresentation(record) {
  return record?.decision_policy_status === "EVALUATED"
    ? decisionActionLabel(record.decision)
    : decisionPolicyStatusLabel(record?.decision_policy_status);
}
