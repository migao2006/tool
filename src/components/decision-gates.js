const GATES = Object.freeze([
  ["1", "data_quality hard gate", "DATA_QUALITY_NOT_EVALUATED"],
  ["2", "tradability gate", "TRADABILITY_NOT_EVALUATED"],
  ["3", "liquidity 與 capacity gate", "CAPACITY_NOT_EVALUATED"],
  ["4", "market_exposure_cap", "MARKET_EXPOSURE_NOT_AVAILABLE"],
  ["5", "calibrated direction probabilities", "DIRECTION_MODEL_NOT_AVAILABLE"],
  ["6", "net quantile thresholds", "QUANTILE_MODEL_NOT_AVAILABLE"],
  ["7", "rank eligibility", "RANK_MODEL_NOT_AVAILABLE"],
  ["8", "position and capacity limits", "POSITION_NOT_EVALUATED"],
]);

export function createDecisionGates() {
  const rows = GATES.map(
    ([step, label, reasonCode]) => `
      <li>
        <span class="gate-step">${step}</span>
        <div class="gate-main"><strong>${label}</strong><code>${reasonCode}</code></div>
        <dl><div><dt>結果</dt><dd>未評估</dd></div><div><dt>實際值</dt><dd>—</dd></div><div><dt>門檻</dt><dd>—</dd></div></dl>
      </li>`,
  ).join("");
  return `<ol class="decision-gates">${rows}</ol>`;
}
