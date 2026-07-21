export const SUPPORTED_HORIZONS = Object.freeze([2, 3, 5, 10]);
export const CURRENT_HORIZON = 5;

export const SYSTEM_STATUS = Object.freeze({
  PASS: "PASS",
  RESEARCH_ONLY: "RESEARCH_ONLY",
  FAIL: "FAIL",
});

export function normalizeHorizon(horizon) {
  const normalized = Number(horizon);
  if (!SUPPORTED_HORIZONS.includes(normalized)) {
    throw new RangeError(`不支援的預測期間：${horizon}`);
  }
  return normalized;
}

export function isReleasedHorizon(horizon) {
  return normalizeHorizon(horizon) === CURRENT_HORIZON;
}

export function createResearchOnlySnapshot(horizon, reasonCode) {
  return Object.freeze({
    horizon: normalizeHorizon(horizon),
    systemStatus: SYSTEM_STATUS.RESEARCH_ONLY,
    reasonCodes: Object.freeze([reasonCode]),
    asOfDate: null,
    decisionAt: null,
    overview: null,
    candidates: Object.freeze([]),
  });
}
