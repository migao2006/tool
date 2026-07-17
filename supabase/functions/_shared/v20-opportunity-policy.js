// Shared v20.1 policy used by the Edge worker adapter and the point-in-time
// research model. Monetary rates below are percentage points, not decimals.

export const V20_MODEL_VERSION = "20.1";
export const SHORT_HORIZONS = Object.freeze([2, 3, 5, 10]);
export const MEDIUM_HORIZONS = Object.freeze([10, 20, 40]);
export const MEDIUM_RESEARCH_HORIZONS = Object.freeze([60]);
export const V20_HORIZONS = Object.freeze({
  short: SHORT_HORIZONS,
  medium: MEDIUM_HORIZONS,
});
export const V20_RESEARCH_HORIZONS = Object.freeze({
  short: Object.freeze([]),
  medium: MEDIUM_RESEARCH_HORIZONS,
});

export const SHORT_WEIGHTS = Object.freeze({
  priceVolumeTrend: 25,
  institutional: 20,
  relativeIndustry: 15,
  volatilityRiskReward: 15,
  marketGlobal: 10,
  revenueEventCatalyst: 10,
  liquidityExecutionCost: 5,
});

export const MEDIUM_WEIGHTS = Object.freeze({
  revenueProfitGrowth: 25,
  financialQuality: 15,
  mediumTrend: 20,
  institutionalPositioning: 15,
  industryEnvironment: 10,
  valuationReasonableness: 10,
  liquidityRisk: 5,
});

export const V20_COST_POLICY_VERSION = "tw-market-cost-2026-07";

const finite = (value) => value !== null && value !== undefined && Number.isFinite(Number(value));
const clamp = (value, low, high) => Math.max(low, Math.min(high, Number(value)));
const round = (value, digits = 4) => finite(value) ? Number(Number(value).toFixed(digits)) : null;

function normalizedGroup(group) {
  const value = String(group || "listed").toLowerCase();
  if (value.includes("etf")) return "etf";
  if (["otc", "tpex", "上櫃"].some((key) => value.includes(key))) return "otc";
  return "listed";
}

export function liquidityGrade(averageDailyValue) {
  if (!finite(averageDailyValue) || Number(averageDailyValue) <= 0) return "unknown";
  const value = Number(averageDailyValue);
  if (value >= 500_000_000) return "A";
  if (value >= 100_000_000) return "B";
  if (value >= 20_000_000) return "C";
  if (value >= 10_000_000) return "D";
  return "E";
}

/**
 * Conservative round-trip cost estimate for Taiwan securities.
 *
 * Commission uses the configured per-side rate (default 0.1425%). When an
 * expected order value is supplied, the usual NT$20 minimum commission is
 * reflected in the effective rate. Tax varies by instrument; spread and
 * slippage vary deterministically with liquidity, volatility, market and
 * price. These are cost assumptions, never a forecast of future return.
 */
export function estimateExecutionCosts({
  group = "listed",
  averageDailyValue = null,
  atrPct = null,
  price = null,
  expectedOrderValue = null,
  commissionRatePerSidePct = 0.1425,
  minimumCommissionTwd = 20,
} = {}) {
  const normalized = normalizedGroup(group);
  const configuredCommission = finite(commissionRatePerSidePct)
    ? Math.max(0, Number(commissionRatePerSidePct))
    : 0.1425;
  const minimumRate = finite(expectedOrderValue) && Number(expectedOrderValue) > 0
    ? Math.max(0, Number(minimumCommissionTwd)) / Number(expectedOrderValue) * 100
    : 0;
  const effectiveCommissionPerSide = Math.max(configuredCommission, minimumRate);

  const value = finite(averageDailyValue) ? Number(averageDailyValue) : null;
  const liquiditySlippage = value === null ? 0.18
    : value >= 500_000_000 ? 0.02
      : value >= 100_000_000 ? 0.04
        : value >= 20_000_000 ? 0.08
          : value >= 10_000_000 ? 0.15
            : 0.30;
  const volatilitySlippage = finite(atrPct)
    ? clamp((Number(atrPct) - 2) * 0.025, 0, 0.22)
    : 0.06;
  const marketSlippage = normalized === "otc" ? 0.025 : normalized === "etf" ? -0.015 : 0;
  const slippagePct = clamp(0.12 + liquiditySlippage + volatilitySlippage + marketSlippage, 0.08, 0.70);

  const priceSpread = finite(price) && Number(price) > 0 && Number(price) < 20 ? 0.045 : 0;
  const marketSpread = normalized === "otc" ? 0.025 : normalized === "etf" ? -0.015 : 0;
  const volatilitySpread = finite(atrPct) ? clamp((Number(atrPct) - 4) * 0.008, 0, 0.08) : 0.02;
  const spreadPct = clamp(0.06 + liquiditySlippage * 0.5 + priceSpread + marketSpread + volatilitySpread, 0.03, 0.45);

  const commissionPct = effectiveCommissionPerSide * 2;
  const taxPct = normalized === "etf" ? 0.1 : 0.3;
  const roundedCommissionPct = round(commissionPct);
  const roundedTaxPct = round(taxPct);
  const roundedSlippagePct = round(slippagePct);
  const roundedSpreadPct = round(spreadPct);
  const totalPct = round(roundedCommissionPct + roundedTaxPct + roundedSlippagePct + roundedSpreadPct);
  return {
    version: V20_COST_POLICY_VERSION,
    basis: "official-tax-and-commission-ceiling-plus-deterministic-market-impact",
    group: normalized,
    liquidityGrade: liquidityGrade(value),
    commissionRatePerSidePct: round(effectiveCommissionPerSide),
    commissionPct: roundedCommissionPct,
    taxPct: roundedTaxPct,
    slippagePct: roundedSlippagePct,
    spreadPct: roundedSpreadPct,
    totalPct,
  };
}

/**
 * Convert a transparent rule score into a cost/risk-adjusted relative score.
 * This is a ranking transform, not an expected-return or probability model.
 */
export function adjustOpportunityScore({
  rawScore,
  riskScore,
  estimatedTotalCostPct,
  model,
  horizonDays,
  atrPct = null,
  expectedTurnoverRate = null,
} = {}) {
  if (![rawScore, riskScore, estimatedTotalCostPct, horizonDays].every(finite) || Number(horizonDays) <= 0) {
    return {
      rawOpportunityScore: finite(rawScore) ? round(clamp(rawScore, 0, 100), 2) : null,
      costPenaltyScore: null,
      downsidePenaltyScore: null,
      turnoverPenaltyScore: null,
      turnoverExposure: null,
      netOpportunityScore: null,
    };
  }

  const key = model === "medium" ? "medium" : "short";
  const referenceHorizon = key === "short" ? 10 : 40;
  const inferredTurnoverExposure = Math.sqrt(referenceHorizon / Number(horizonDays));
  const turnoverExposure = finite(expectedTurnoverRate)
    ? clamp(Number(expectedTurnoverRate), 0, 4)
    : clamp(inferredTurnoverExposure, 0.25, 3);
  const costPct = Math.max(0, Number(estimatedTotalCostPct));
  const costPenaltyScore = clamp(costPct * 4, 0, 100);
  const volatilityPenalty = finite(atrPct) ? Math.max(0, Number(atrPct) - 4) * 0.35 : 0;
  const downsidePenaltyScore = clamp(
    clamp(Number(riskScore), 0, 100) * (key === "short" ? 0.12 : 0.10) + volatilityPenalty,
    0,
    100,
  );
  const turnoverPenaltyScore = clamp(costPct * turnoverExposure * (key === "short" ? 1.35 : 0.85), 0, 100);
  const netOpportunityScore = clamp(
    Number(rawScore) - costPenaltyScore - downsidePenaltyScore - turnoverPenaltyScore,
    0,
    100,
  );
  return {
    rawOpportunityScore: round(clamp(rawScore, 0, 100), 2),
    costPenaltyScore: round(costPenaltyScore, 2),
    downsidePenaltyScore: round(downsidePenaltyScore, 2),
    turnoverPenaltyScore: round(turnoverPenaltyScore, 2),
    turnoverExposure: round(turnoverExposure, 4),
    netOpportunityScore: round(netOpportunityScore, 2),
  };
}
